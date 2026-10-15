"""Project-scoped vector retrieval for question answering."""

from __future__ import annotations

import requests

from src.config import AppConfig
from src.index_store import IndexStoreError, ProjectIndexStore, project_key
from src.models import RetrievedChunk
from src.ollama_client import local_session
from src.errors import OllamaConnectionError


class RetrievalError(RuntimeError):
    """Raised when a question cannot be searched against the active index."""


def _embed_query(question: str, config: AppConfig) -> list[float]:
    try:
        with local_session(config) as session:
            response = session.post(
                f"{config.ollama_url}/api/embed",
                json={"model": config.embedding_model, "input": question},
                timeout=config.request_timeout_seconds,
            )
            response.raise_for_status()
            embeddings = response.json().get("embeddings", [])
        if not embeddings or not isinstance(embeddings[0], list):
            raise ValueError("Ollama returned no query embedding")
        return embeddings[0]
    except (requests.RequestException, ValueError) as exc:
        raise RetrievalError(f"Could not search with `{config.embedding_model}`: {exc}") from exc


def retrieve(
    project_root: str,
    question: str,
    config: AppConfig,
    *,
    top_k: int = 6,
) -> list[RetrievedChunk]:
    store = ProjectIndexStore(project_key(project_root))
    manifest = store.load_manifest()
    if not manifest or not manifest.get("active_collection"):
        raise RetrievalError("This project has not been indexed yet. Build its index first.")
    if manifest.get("project_root") != project_root:
        raise RetrievalError("The active index belongs to a different project. Rebuild it first.")
    if manifest.get("embedding_model") != config.embedding_model:
        raise RetrievalError(
            "The embedding model changed since the last index. Refresh the project index before asking."
        )
    if int(manifest.get("chunk_count", 0)) == 0:
        return []

    try:
        collection = store.get_collection(manifest["active_collection"])
        result = collection.query(
            query_embeddings=[_embed_query(question, config)],
            n_results=min(top_k, int(manifest["chunk_count"])),
            include=["documents", "metadatas", "distances"],
        )
    except (IndexStoreError, OllamaConnectionError, requests.RequestException, ValueError) as exc:
        raise RetrievalError(str(exc)) from exc
    except Exception as exc:
        raise RetrievalError(f"Could not search the local index: {exc}") from exc

    ids = (result.get("ids") or [[]])[0]
    documents = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    matches: list[RetrievedChunk] = []
    for index, metadata in enumerate(metadatas):
        if not metadata or metadata.get("project_key") != store.project_key:
            continue
        if metadata.get("source_path") not in manifest.get("files", {}):
            continue
        distance = float(distances[index]) if index < len(distances) else None
        if distance is not None and distance > 1.0 - config.min_similarity:
            continue
        matches.append(
            RetrievedChunk(
                chunk_id=ids[index],
                source_path=str(metadata["source_path"]),
                start_line=int(metadata["start_line"]),
                end_line=int(metadata["end_line"]),
                text=documents[index] or "",
                distance=distance,
            )
        )
    return matches
