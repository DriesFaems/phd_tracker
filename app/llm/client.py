"""Thin wrapper around Ollama's /api/chat endpoint."""

import json
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _payload(messages: list[dict], fmt: dict | str | None) -> dict:
    s = get_settings()
    body: dict = {
        "model": s.ollama_model,
        "messages": messages,
        "stream": False,
        "keep_alive": s.ollama_keep_alive,
        "options": {"temperature": 0.2 if fmt else 0.5},
    }
    if fmt:
        body["format"] = fmt
    if s.ollama_think:
        body["think"] = s.ollama_think.lower() == "true"
    return body


def chat(messages: list[dict], fmt: dict | str | None = None) -> str:
    s = get_settings()
    try:
        resp = httpx.post(
            f"{s.ollama_url.rstrip('/')}/api/chat", json=_payload(messages, fmt), timeout=s.ollama_timeout
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMError(f"Ollama returned {exc.response.status_code}: {exc.response.text[:300]}") from exc
    except httpx.TimeoutException as exc:
        raise LLMError(
            f"Ollama did not answer within {s.ollama_timeout:.0f}s (the model may still be loading or the server is busy). Try again."
        ) from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"Could not reach Ollama at {s.ollama_url}: {exc}") from exc
    content = resp.json().get("message", {}).get("content", "")
    return _THINK_BLOCK.sub("", content).strip()


def chat_json(messages: list[dict], schema: type[T]) -> T:
    """Ask for JSON matching `schema`, retrying once with the validation error if the model slips."""
    last_error = ""
    for _ in range(2):
        msgs = messages if not last_error else messages + [
            {"role": "user", "content": f"Your previous answer was not valid ({last_error}). Reply with JSON only."}
        ]
        raw = chat(msgs, fmt=schema.model_json_schema())
        try:
            return schema.model_validate(json.loads(_strip_fences(raw)))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = str(exc)[:300]
    raise LLMError(f"Model did not return valid JSON: {last_error}")


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0]
    return text


def health() -> tuple[bool, str]:
    s = get_settings()
    try:
        resp = httpx.get(f"{s.ollama_url.rstrip('/')}/api/tags", timeout=5)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        return False, f"Ollama unreachable at {s.ollama_url} ({exc.__class__.__name__})"
    names = [m.get("name", "") for m in resp.json().get("models", [])]
    if not any(n == s.ollama_model or n.split(":")[0] == s.ollama_model for n in names):
        return False, f"Ollama is up but model '{s.ollama_model}' is not installed (have: {', '.join(names) or 'none'})"
    return True, f"{s.ollama_model} ready"
