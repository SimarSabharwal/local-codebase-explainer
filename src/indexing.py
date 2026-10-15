"""Full and incremental local index construction."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import requests

from src.config import AppConfig
from src.discovery import scan_project
from src.index_store import IndexStoreError, ProjectIndexStore, project_key
from src.models import ScanReport
from src.ollama_client import check_connection, local_session
from src.parsing import FileParseError, read_and_chunk

ProgressCallback = Callable[[float, str], None]


class IndexingError(RuntimeError):
    """Raised when a new index generation cannot be completed."""


def _embed(texts: list[str], config: AppConfig) -> list[list[float]]:
    try:
        with local_session(config) as session:
            response = session.post(
                f"{config.ollama_url}/api/embed",
                json={"model": config.embedding_model, "input": texts},
                timeout=config.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(texts):
            raise ValueError("Ollama returned an unexpected number of embeddings")
        return embeddings
    except (requests.RequestException, ValueError) as exc:
        raise IndexingError(
            f"Could not create local embeddings with `{config.embedding_model}`: {exc}"
        ) from exc


def build_index(
    project_root: str,
    config: AppConfig,
    *,
    incremental: bool = True,
    progress: ProgressCallback | None = None,
) -> tuple[ScanReport, dict]:
    """Build a new index generation, then atomically make it active."""
    if progress:
        progress(0.02, "Scanning project files")
    report = scan_project(
        project_root,
        max_file_bytes=config.max_file_bytes,
        progress=(lambda message: progress(0.05, message)) if progress else None,
    )
    if report.error:
        raise IndexingError(report.error)
    try:
        check_connection(config)
    except Exception as exc:
        raise IndexingError(str(exc)) from exc

    store = ProjectIndexStore(project_key(report.root))
    old_manifest = store.load_manifest()
    if old_manifest and old_manifest.get("project_root") != report.root:
        # A theoretical hash collision must never allow one project's data to be reused.
        old_manifest = None
    can_reuse = bool(
        incremental
        and old_manifest
        and old_manifest.get("embedding_model") == config.embedding_model
        and old_manifest.get("chunk_lines") == config.chunk_lines
        and old_manifest.get("overlap_lines") == config.overlap_lines
        and old_manifest.get("max_file_bytes") == config.max_file_bytes
        and old_manifest.get("active_collection")
    )
    old_files = old_manifest.get("files", {}) if can_reuse else {}
    current = {item.relative_path: item for item in report.files}
    unchanged = {
        path
        for path, item in current.items()
        if path in old_files
        and old_files[path].get("content_hash") == item.content_hash
    }
    changed_items = [item for item in report.files if item.relative_path not in unchanged]

    parsed_files: dict[str, dict] = {}
    changed_chunks = []
    parsing_skips = []
    for index, item in enumerate(changed_items):
        if progress:
            fraction = 0.08 + (0.28 * (index / max(1, len(changed_items))))
            progress(fraction, f"Reading {item.relative_path}")
        try:
            chunks, content_hash = read_and_chunk(item, config)
        except FileParseError as exc:
            parsing_skips.append({"path": item.relative_path, "reason": str(exc)})
            continue
        parsed_files[item.relative_path] = {
            "size_bytes": item.size_bytes,
            "modified_ns": item.modified_ns,
            "content_hash": content_hash,
            "chunk_count": len(chunks),
        }
        changed_chunks.extend(chunks)

    new_file_manifest = {
        path: {
            **old_files[path],
            "size_bytes": current[path].size_bytes,
            "modified_ns": current[path].modified_ns,
        }
        for path in unchanged
    }
    new_file_manifest.update(parsed_files)

    old_rows = None
    if can_reuse:
        try:
            old_collection = store.get_collection(old_manifest["active_collection"])
            old_rows = old_collection.get(include=["documents", "metadatas", "embeddings"])
        except IndexStoreError as exc:
            # A stale/missing collection should result in a clean rebuild instead of data loss.
            old_rows = None
            unchanged.clear()
            changed_items = report.files
            new_file_manifest.clear()
            changed_chunks = []
            parsed_files.clear()
            parsing_skips.clear()
            for item in changed_items:
                try:
                    chunks, content_hash = read_and_chunk(item, config)
                except FileParseError as parse_exc:
                    parsing_skips.append({"path": item.relative_path, "reason": str(parse_exc)})
                    continue
                parsed_files[item.relative_path] = {
                    "size_bytes": item.size_bytes,
                    "modified_ns": item.modified_ns,
                    "content_hash": content_hash,
                    "chunk_count": len(chunks),
                }
                changed_chunks.extend(chunks)
            new_file_manifest.update(parsed_files)

    try:
        collection_name, collection = store.create_collection()
        # Copy vectors for unchanged files into the new generation. The manifest switch
        # happens only after all additions succeed, leaving the previous generation usable.
        if old_rows and unchanged:
            ids = old_rows.get("ids", [])
            documents = old_rows.get("documents", [])
            metadatas = old_rows.get("metadatas", [])
            embeddings = old_rows.get("embeddings", [])
            keep_indices = [
                index
                for index, metadata in enumerate(metadatas)
                if metadata and metadata.get("source_path") in unchanged
            ]
            for start in range(0, len(keep_indices), 500):
                batch = keep_indices[start : start + 500]
                collection.add(
                    ids=[ids[i] for i in batch],
                    documents=[documents[i] for i in batch],
                    metadatas=[metadatas[i] for i in batch],
                    embeddings=[embeddings[i].tolist() if hasattr(embeddings[i], "tolist") else embeddings[i] for i in batch],
                )

        for start in range(0, len(changed_chunks), 32):
            batch = changed_chunks[start : start + 32]
            vectors = _embed([chunk.text for chunk in batch], config)
            collection.add(
                ids=[chunk.chunk_id for chunk in batch],
                documents=[chunk.text for chunk in batch],
                metadatas=[
                    {
                        "project_key": store.project_key,
                        "source_path": chunk.source_path,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "content_hash": chunk.content_hash,
                    }
                    for chunk in batch
                ],
                embeddings=vectors,
            )
            if progress:
                fraction = 0.4 + (0.52 * min(1, (start + len(batch)) / max(1, len(changed_chunks))))
                progress(fraction, f"Indexing snippets ({start + len(batch)} of {len(changed_chunks)})")

        manifest = {
            "project_root": report.root,
            "project_key": store.project_key,
            "active_collection": collection_name,
            "embedding_model": config.embedding_model,
            "chunk_lines": config.chunk_lines,
            "overlap_lines": config.overlap_lines,
            "max_file_bytes": config.max_file_bytes,
            "files": new_file_manifest,
            "file_count": len(new_file_manifest),
            "chunk_count": collection.count(),
            "last_refresh": datetime.now(timezone.utc).isoformat(),
        }
        store.write_manifest(manifest)
        store.clean_old_collections(keep=collection_name)
    except (IndexStoreError, requests.RequestException, ValueError) as exc:
        raise IndexingError(str(exc)) from exc
    except Exception as exc:
        raise IndexingError(f"Indexing did not complete: {exc}") from exc

    if progress:
        progress(1.0, "Index ready")
    result = {
        "files_indexed": len(new_file_manifest),
        "chunks_indexed": int(manifest["chunk_count"]),
        "incremental": can_reuse and incremental,
        "last_refresh": manifest["last_refresh"],
        "skipped": parsing_skips,
    }
    return report, result
