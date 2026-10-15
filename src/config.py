"""Application configuration and local data directory helpers."""

from __future__ import annotations

import os
import ipaddress
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class AppConfig:
    ollama_url: str = "http://localhost:11434"
    chat_model: str = "llama3.2"
    embedding_model: str = "nomic-embed-text"
    max_file_bytes: int = 2 * 1024 * 1024
    chunk_lines: int = 100
    overlap_lines: int = 15
    request_timeout_seconds: int = 60
    max_context_chars: int = 18000
    min_similarity: float = 0.2


@dataclass(frozen=True)
class OllamaStatus:
    chat_model: str
    embedding_model: str


def local_data_dir() -> Path:
    """Return an OS-appropriate per-user application data directory."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif os.uname().sysname == "Darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "LocalCodebaseExplainer"


def is_loopback_url(url: str) -> bool:
    """Return whether an Ollama URL resolves syntactically to this device."""
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold().rstrip(".")
        if parsed.scheme not in {"http", "https"}:
            return False
        if parsed.username or parsed.password:
            return False
        if host == "localhost":
            return True
        return ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        return False
