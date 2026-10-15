"""Shared records for discovery and later indexing stages."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiscoveredFile:
    absolute_path: str
    relative_path: str
    size_bytes: int
    modified_ns: int
    content_hash: str


@dataclass(frozen=True)
class SkippedPath:
    path: str
    reason: str


@dataclass(frozen=True)
class ScanReport:
    root: str
    files: list[DiscoveredFile]
    skipped: list[SkippedPath]
    error: str | None = None

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


@dataclass(frozen=True)
class TextChunk:
    chunk_id: str
    source_path: str
    start_line: int
    end_line: int
    text: str
    content_hash: str


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: str
    source_path: str
    start_line: int
    end_line: int
    text: str
    distance: float | None = None

    @property
    def citation(self) -> str:
        return f"[{self.source_path}:L{self.start_line}-L{self.end_line}]"
