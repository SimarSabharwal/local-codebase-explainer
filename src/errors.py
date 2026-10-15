"""Application-facing errors with actionable messages."""


class OllamaConnectionError(RuntimeError):
    """Raised when the configured local Ollama service cannot be reached."""


class OllamaModelError(RuntimeError):
    """Raised when an expected local model is not available."""


class ProjectSelectionError(ValueError):
    """Raised when a project path is invalid or unreadable."""
