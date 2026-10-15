"""Safe project file discovery with practical ignore handling."""

from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path
from typing import Callable

from src.models import DiscoveredFile, ScanReport, SkippedPath


SUPPORTED_EXTENSIONS = {
    ".c", ".cc", ".cpp", ".cs", ".css", ".csv", ".dart", ".ex", ".exs",
    ".go", ".h", ".hpp", ".html", ".java", ".js", ".json", ".jsx", ".kt",
    ".lua", ".md", ".mjs", ".php", ".py", ".rb", ".rs", ".rst", ".scala",
    ".scss", ".sh", ".sql", ".svelte", ".swift", ".toml", ".ts", ".tsx",
    ".txt", ".vue", ".xml", ".yaml", ".yml", ".zsh",
}

ALWAYS_IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".idea", ".vscode", "__pycache__", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".tox", ".venv", "venv", "env", ".next", ".nuxt",
    "node_modules", "bower_components", "vendor", "dist", "build", "target",
    "out", "coverage", "site-packages", "Pods", "DerivedData", ".terraform",
    ".gradle", "bin", "obj",
}

SECRET_NAMES = {
    ".env", ".envrc", ".npmrc", ".pypirc", ".netrc", ".env.local",
    ".env.production", "secrets.json", "secrets.yaml", "secrets.yml",
    "credentials.json", "id_rsa", "id_ed25519",
}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx", ".keystore"}


def _is_link(path: Path) -> bool:
    is_junction = getattr(path, "is_junction", None)
    return path.is_symlink() or bool(is_junction and is_junction())


def _is_secret_file(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered in SECRET_NAMES
        or lowered.startswith(".env.")
        or lowered.endswith(".env")
        or any(lowered.endswith(suffix) for suffix in SECRET_SUFFIXES)
    )


def _load_gitignore(root: Path) -> tuple[object | None, list[str]]:
    ignore_file = root / ".gitignore"
    try:
        lines = ignore_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None, []

    try:
        import pathspec

        return pathspec.PathSpec.from_lines("gitwildmatch", lines), []
    except ImportError:
        # Keep discovery usable without the optional matcher. The dependency in
        # requirements.txt provides full Git wildmatch semantics in normal use.
        patterns = [
            line.strip().replace("\\ ", " ")
            for line in lines
            if line.strip() and not line.lstrip().startswith("#")
        ]
        return None, patterns


def _ignored_by_fallback(relative_path: str, patterns: list[str]) -> bool:
    """Handle common .gitignore glob, directory, and root-anchored patterns."""
    normalized = relative_path.replace(os.sep, "/")
    parts = normalized.split("/")
    ignored = False
    for raw_pattern in patterns:
        negated = raw_pattern.startswith("!")
        pattern = raw_pattern[1:] if negated else raw_pattern
        directory_only = pattern.endswith("/")
        pattern = pattern.strip("/")
        anchored = raw_pattern.startswith("/")
        matched = False
        if anchored or "/" in pattern:
            matched = fnmatch.fnmatchcase(normalized, pattern) or any(
                fnmatch.fnmatchcase("/".join(parts[:index]), pattern)
                for index in range(1, len(parts))
            )
        else:
            matched = any(fnmatch.fnmatchcase(part, pattern) for part in parts)
        if directory_only:
            matched = matched and len(parts) > 1
        if matched:
            ignored = not negated
    return ignored


def scan_project(
    project_path: str,
    max_file_bytes: int,
    progress: Callable[[str], None] | None = None,
) -> ScanReport:
    """Scan a project without opening or executing any file contents."""
    candidate = Path(project_path).expanduser()
    if not str(project_path).strip():
        return ScanReport("", [], [], "Enter a project folder path.")
    try:
        root = candidate.resolve(strict=True)
    except OSError:
        return ScanReport("", [], [], "The selected folder does not exist or cannot be opened.")
    if not root.is_dir():
        return ScanReport(str(root), [], [], "The selected path is not a folder.")

    files: list[DiscoveredFile] = []
    skipped: list[SkippedPath] = []
    gitignore_spec, fallback_patterns = _load_gitignore(root)
    examined = 0

    def record_skip(relative: str, reason: str) -> None:
        # Bound the UI payload for very large repositories while retaining a useful summary.
        if len(skipped) < 5000:
            skipped.append(SkippedPath(relative or ".", reason))

    for current_dir, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_dir)
        retained_dirs: list[str] = []
        for dirname in sorted(dirnames):
            directory_path = current / dirname
            relative_dir = directory_path.relative_to(root).as_posix()
            if _is_link(directory_path):
                record_skip(relative_dir, "Linked folders are not followed")
                continue
            if dirname.lower() in ALWAYS_IGNORED_DIRS:
                record_skip(relative_dir, "Generated, dependency, or version-control folder")
                continue
            if _is_secret_file(dirname):
                record_skip(relative_dir, "Secret-like folder excluded by default")
                continue
            ignored = (
                gitignore_spec.match_file(relative_dir + "/")
                if gitignore_spec is not None
                else _ignored_by_fallback(relative_dir + "/", fallback_patterns)
            )
            if ignored:
                record_skip(relative_dir, "Excluded by .gitignore")
                continue
            retained_dirs.append(dirname)
        dirnames[:] = retained_dirs

        for filename in sorted(filenames):
            examined += 1
            if progress and examined % 100 == 0:
                progress(f"Scanning files… {examined} checked")
            absolute = current / filename
            relative = absolute.relative_to(root).as_posix()
            if _is_secret_file(filename):
                record_skip(relative, "Secret-like file excluded by default")
                continue
            ignored = (
                gitignore_spec.match_file(relative)
                if gitignore_spec is not None
                else _ignored_by_fallback(relative, fallback_patterns)
            )
            if ignored:
                record_skip(relative, "Excluded by .gitignore")
                continue
            if absolute.suffix.lower() not in SUPPORTED_EXTENSIONS:
                record_skip(relative, "Unsupported file type")
                continue
            try:
                if _is_link(absolute):
                    record_skip(relative, "Linked files are not indexed")
                    continue
                stat = absolute.stat()
            except OSError:
                record_skip(relative, "File cannot be read")
                continue
            if stat.st_size > max_file_bytes:
                record_skip(relative, f"File exceeds the {max_file_bytes // (1024 * 1024)} MB size limit")
                continue
            try:
                raw = absolute.read_bytes()
            except OSError:
                record_skip(relative, "File cannot be read")
                continue
            if len(raw) > max_file_bytes:
                record_skip(relative, "File grew beyond the configured size limit during scanning")
                continue
            if b"\x00" in raw:
                record_skip(relative, "Binary file")
                continue
            files.append(
                DiscoveredFile(
                    absolute_path=str(absolute),
                    relative_path=relative,
                    size_bytes=stat.st_size,
                    modified_ns=stat.st_mtime_ns,
                    content_hash=hashlib.sha256(raw).hexdigest(),
                )
            )

    if progress:
        progress(f"Scan complete · {len(files)} supported files · {len(skipped)} skipped")
    return ScanReport(str(root), files, skipped)
