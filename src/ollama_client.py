"""Small HTTP client for a local Ollama service."""

from __future__ import annotations

import requests

from src.config import AppConfig, OllamaStatus, is_loopback_url
from src.errors import OllamaConnectionError, OllamaModelError


def local_session(config: AppConfig) -> requests.Session:
    """Create a session that cannot route local prompts through environment proxies."""
    if not is_loopback_url(config.ollama_url):
        raise OllamaConnectionError(
            "For privacy, Ollama must use a localhost or loopback address without credentials."
        )
    session = requests.Session()
    session.trust_env = False
    return session


def check_connection(config: AppConfig) -> OllamaStatus:
    """Check the local service and confirm both configured models are present."""
    try:
        with local_session(config) as session:
            response = session.get(
                f"{config.ollama_url}/api/tags",
                timeout=min(config.request_timeout_seconds, 10),
            )
            response.raise_for_status()
            payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise OllamaConnectionError(
            f"Could not reach {config.ollama_url}. Start Ollama and try again."
        ) from exc

    available = {str(model.get("name", "")) for model in payload.get("models", [])}

    def model_present(name: str) -> bool:
        if not name:
            return False
        return name in available or (":" not in name and f"{name}:latest" in available)

    missing = [name for name in (config.chat_model, config.embedding_model) if not model_present(name)]
    if not config.chat_model or not config.embedding_model:
        raise OllamaModelError("Enter both a chat model name and an embedding model name.")
    if missing:
        model_list = ", ".join(f"`{name}`" for name in missing)
        raise OllamaModelError(
            f"Pull the configured model(s) in Ollama before continuing: {model_list}. "
            "For example, run `ollama pull <model-name>`."
        )

    return OllamaStatus(config.chat_model, config.embedding_model)
