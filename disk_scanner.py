"""Read-only disk usage scanner.

Uses only os.scandir / pathlib / os.statvfs — never creates, modifies,
deletes, moves, chmod, or writes under scanned paths.
"""

from __future__ import annotations

import heapq
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class PathSize:
    path: str
    size_bytes: int


@dataclass(frozen=True)
class VolumeInfo:
    path: str
    total_bytes: int
    free_bytes: int
    available_bytes: int


@dataclass(frozen=True)
class ScanResult:
    target: str
    total_bytes: int
    folders: list[PathSize]
    files: list[PathSize]
    errors: list[str]
    entries_seen: int


def human_size(num_bytes: int) -> str:
    """Format byte count as a short human-readable string."""
    if num_bytes < 0:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    value = float(num_bytes)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def resolve_existing_dir(raw: str) -> Path:
    """Resolve a path and ensure it is an existing directory (read-only checks)."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Путь не указан.")
    path = Path(text).expanduser()
    try:
        path = path.resolve(strict=False)
    except OSError as exc:
        raise ValueError(f"Не удалось разрешить путь: {exc}") from exc
    if not path.exists():
        raise FileNotFoundError(f"Путь не существует: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Это не каталог: {path}")
    if not os.access(path, os.R_OK | os.X_OK):
        raise PermissionError(f"Нет прав на чтение каталога: {path}")
    return path


def volume_info(path: Path) -> VolumeInfo | None:
    """Read volume capacity for the filesystem containing path (read-only)."""
    try:
        st = os.statvfs(path)
    except (OSError, AttributeError):
        return None
    # Prefer fragment size when available; fall back to block size.
    frsize = st.f_frsize or st.f_bsize or 1
    total = st.f_blocks * frsize
    free = st.f_bfree * frsize
    available = st.f_bavail * frsize
    return VolumeInfo(
        path=str(path),
        total_bytes=total,
        free_bytes=free,
        available_bytes=available,
    )


def _safe_entry_size(entry: os.DirEntry) -> int | None:
    try:
        if entry.is_symlink():
            return None
        if entry.is_file(follow_symlinks=False):
            return entry.stat(follow_symlinks=False).st_size
    except OSError:
        return None
    return None


def _walk_tree(
    root: Path,
    errors: list[str],
    max_errors: int = 50,
) -> Iterator[tuple[str, int, bool]]:
    """Yield (path, size_bytes, is_dir) for files; directories reported separately via aggregation."""
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                            continue
                        if entry.is_file(follow_symlinks=False):
                            size = _safe_entry_size(entry)
                            if size is not None:
                                yield entry.path, size, False
                    except PermissionError as exc:
                        if len(errors) < max_errors:
                            errors.append(f"Нет доступа: {entry.path} ({exc})")
                    except OSError as exc:
                        if len(errors) < max_errors:
                            errors.append(f"Ошибка чтения: {entry.path} ({exc})")
        except PermissionError as exc:
            if len(errors) < max_errors:
                errors.append(f"Нет доступа к каталогу: {current} ({exc})")
        except OSError as exc:
            if len(errors) < max_errors:
                errors.append(f"Ошибка сканирования: {current} ({exc})")


def scan_directory(target: Path, top_n: int = 20) -> ScanResult:
    """Scan target recursively (read-only) and return heaviest folders/files."""
    errors: list[str] = []
    # Min-heap of (size, path) for top files — bounded memory.
    top_files_heap: list[tuple[int, str]] = []
    folder_bytes: dict[str, int] = {str(target): 0}
    entries_seen = 0
    target_s = str(target)
    n = max(1, top_n)

    for file_path, size, _ in _walk_tree(target, errors):
        entries_seen += 1
        if len(top_files_heap) < n:
            heapq.heappush(top_files_heap, (size, file_path))
        elif size > top_files_heap[0][0]:
            heapq.heapreplace(top_files_heap, (size, file_path))

        p = Path(file_path)
        try:
            rel = p.relative_to(target)
        except ValueError:
            continue
        parts = rel.parts
        for depth in range(len(parts)):
            ancestor = target.joinpath(*parts[:depth]) if depth else target
            key = str(ancestor)
            folder_bytes[key] = folder_bytes.get(key, 0) + size

    folders = [
        PathSize(path=path_str, size_bytes=size)
        for path_str, size in folder_bytes.items()
        if path_str != target_s
    ]
    folders.sort(key=lambda x: x.size_bytes, reverse=True)

    top_files_heap.sort(key=lambda x: x[0], reverse=True)
    files = [PathSize(path=path, size_bytes=size) for size, path in top_files_heap]

    total = folder_bytes.get(target_s, 0)
    return ScanResult(
        target=target_s,
        total_bytes=total,
        folders=folders[:n],
        files=files,
        errors=errors,
        entries_seen=entries_seen,
    )


def is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False
