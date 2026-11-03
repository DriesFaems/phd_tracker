from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    secret_key: str = "change-me-in-production"
    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'app.db').as_posix()}"
    # Public URL of the app, used to build invite links.
    base_url: str = "http://localhost:8000"
    # Set to true behind HTTPS so the session cookie is only sent over TLS.
    secure_cookies: bool = False

    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4"
    ollama_timeout: float = 300.0
    # How long Ollama keeps the model in memory after a request; avoids slow cold starts.
    ollama_keep_alive: str = "60m"
    # Leave empty to not send the `think` flag; "false" disables reasoning on models that support it.
    ollama_think: str = ""

    invite_valid_days: int = 14


@lru_cache
def get_settings() -> Settings:
    return Settings()
