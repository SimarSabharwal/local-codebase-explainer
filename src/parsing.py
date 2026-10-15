"""Text decoding and line-preserving chunking."""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.config import AppConfig
from src.models import DiscoveredFile, TextChunk


class FileParseError(ValueError):
    """A discovered file could not be safely decoded as text."""


def read_and_chunk(item: DiscoveredFile, config: AppConfig) -> tuple[list[TextChunk], str]:
    """Read a file as text and return bounded chunks with original line ranges."""
    path = Path(item.absolute_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise FileParseError("File cannot be read") from exc
    if len(raw) > config.max_file_bytes:
        raise FileParseError("File exceeded the configured size limit during reading")
    if b"\x00" in raw:
        raise FileParseError("Binary file")

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise FileParseError("File encoding is not supported") from exc

    # Remove a UTF-8 BOM if the file was decoded via an alternate path.
    text = text.lstrip("\ufeff")
    lines = text.splitlines()
    digest = hashlib.sha256(raw).hexdigest()
    if not lines:
        return [], digest

    chunk_size = max(1, config.chunk_lines)
    overlap = min(max(0, config.overlap_lines), chunk_size - 1)
    step = chunk_size - overlap
    chunks: list[TextChunk] = []
    for start in range(0, len(lines), step):
        end = min(start + chunk_size, len(lines))
        body = "\n".join(lines[start:end])
        identity = f"{item.relative_path}\0{start + 1}\0{end}\0{digest}"
        chunk_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        chunks.append(
            TextChunk(
                chunk_id=chunk_id,
                source_path=item.relative_path,
                start_line=start + 1,
                end_line=end,
                text=body,
                content_hash=digest,
            )
        )
        if end == len(lines):
            break

    return chunks, digest
