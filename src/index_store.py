"""Per-project Chroma persistence and atomic index manifests."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from src.config import local_data_dir


class IndexStoreError(RuntimeError):
    """Raised when the local index cannot be opened or updated."""


class ProjectIndexStore:
    def __init__(self, project_key: str):
        self.project_key = project_key
        self.root = local_data_dir() / "indexes"
        self.manifest_dir = local_data_dir() / "projects" / project_key
        self.manifest_path = self.manifest_dir / "manifest.json"
        self._client_instance = None

    @property
    def collection_prefix(self) -> str:
        return f"project_{self.project_key}_g"

    def _client(self):
        if self._client_instance is not None:
            return self._client_instance
        try:
            import chromadb
            from chromadb.config import Settings
        except ImportError as exc:
            raise IndexStoreError(
                "ChromaDB is not installed. Install project dependencies with "
                "`python -m pip install -r requirements.txt`."
            ) from exc
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self._client_instance = chromadb.PersistentClient(
                path=str(self.root),
                settings=Settings(anonymized_telemetry=False),
            )
            return self._client_instance
        except Exception as exc:  # Chroma may wrap storage/locking errors.
            raise IndexStoreError(f"Could not open the local index: {exc}") from exc

    def load_manifest(self) -> dict[str, Any] | None:
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise IndexStoreError(f"The saved index manifest cannot be read: {exc}") from exc

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        self.manifest_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_suffix(".json.tmp")
        try:
            temporary.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temporary, self.manifest_path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise IndexStoreError(f"Could not save index state: {exc}") from exc

    def get_collection(self, name: str):
        try:
            return self._client().get_collection(name=name)
        except Exception as exc:
            raise IndexStoreError("The saved project index is missing or unreadable. Rebuild it.") from exc

    def create_collection(self):
        generation = uuid.uuid4().hex[:16]
        name = f"{self.collection_prefix}{generation}"
        try:
            collection = self._client().create_collection(
                name=name,
                metadata={"hnsw:space": "cosine", "project_key": self.project_key},
            )
        except Exception as exc:
            raise IndexStoreError(f"Could not create a local index collection: {exc}") from exc
        return name, collection

    def delete_collection(self, name: str) -> None:
        try:
            self._client().delete_collection(name=name)
        except Exception:
            # The manifest remains the source of truth; orphan cleanup is best effort.
            return

    def clean_old_collections(self, keep: str | None) -> None:
        try:
            client = self._client()
            collections = client.list_collections()
            names = [item.name if hasattr(item, "name") else str(item) for item in collections]
        except Exception:
            return
        for name in names:
            if name.startswith(self.collection_prefix) and name != keep:
                self.delete_collection(name)

    def clear(self) -> None:
        try:
            client = self._client()
            collections = client.list_collections()
            names = [item.name if hasattr(item, "name") else str(item) for item in collections]
            for name in names:
                if name.startswith(self.collection_prefix):
                    client.delete_collection(name=name)
        except Exception as exc:
            raise IndexStoreError(f"Could not remove this project's local index: {exc}") from exc
        try:
            self.manifest_path.unlink(missing_ok=True)
            if self.manifest_dir.exists():
                self.manifest_dir.rmdir()
        except OSError as exc:
            raise IndexStoreError(f"Could not clear the project index state: {exc}") from exc

    def collection_count(self, name: str) -> int:
        return int(self.get_collection(name).count())


def project_key(project_root: str) -> str:
    """Create a stable, non-reversible identifier from the canonical root path."""
    import hashlib

    normalized = os.path.normcase(str(Path(project_root).resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
