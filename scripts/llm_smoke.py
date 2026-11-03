"""Check the real Ollama/Gemma setup: health, one extraction and one free-text answer, with timings.

Usage:  .venv\\Scripts\\python -m scripts.llm_smoke
"""

import time

from app.config import get_settings
from app.llm import client, prompts

SAMPLE_LOG = """Paper 1 (CVC): finished the discussion section and sent the full draft.
Paper 2 (alliances): my instrument is weak (F=4). Not sure whether to use Heckman or reframe as descriptive - would love your input.
Also attended a workshop on qualitative methods."""

PROJECTS = [
    {"id": 1, "title": "Corporate venturing and ambidexterity", "stage": "Writing", "description": "Case study of CVC units"},
    {"id": 2, "title": "Alliance governance in deep tech", "stage": "Analysis", "description": "Panel data on biotech alliances"},
    {"id": 3, "title": "Effectual decision-making of scientists", "stage": "Design", "description": "Experiments"},
]


def main() -> None:
    s = get_settings()
    print(f"Ollama: {s.ollama_url}  model: {s.ollama_model}")
    ok, msg = client.health()
    print("health:", msg)
    if not ok:
        return

    t = time.perf_counter()
    result = client.chat_json(prompts.extract_messages(PROJECTS, SAMPLE_LOG, []), prompts.Extraction)
    print(f"\nextraction ({time.perf_counter() - t:.1f}s):\n{result.model_dump_json(indent=2)}")

    t = time.perf_counter()
    text = client.chat(prompts.feedback_messages("Anna", SAMPLE_LOG))
    print(f"\nfeedback draft ({time.perf_counter() - t:.1f}s):\n{text}")


if __name__ == "__main__":
    main()
