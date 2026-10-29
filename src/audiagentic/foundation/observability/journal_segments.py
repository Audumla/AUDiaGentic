"""Dated immutable segments for indexed append-only NDJSON journals.

Callers own policy and eligibility. This module only rotates a locked head,
streams its segments, and performs explicitly authorized segment maintenance.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
import re
import shutil
import stat
import tempfile
import threading
import uuid
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from audiagentic.foundation.system.advisory_lock import AdvisoryLock
from audiagentic.foundation.system.process import StartupLock

_SEGMENT = re.compile(r"^\d{4}-\d{2}-\d{2}\.\d{20}\.[0-9a-f]{32}\.ndjson(?:\.gz)?$")
_HELD = threading.local()
logger = logging.getLogger(__name__)


def segment_directory(path: Path) -> Path:
    return path.with_name(path.name + ".segments")


@contextmanager
def journal_lock(path: Path):
    """Cross-process writer fence, reentrant for nested snapshot reads."""
    key = os.path.normcase(os.path.abspath(path))
    pid = os.getpid()
    held = getattr(_HELD, "paths", set()) if getattr(_HELD, "pid", None) == pid else set()
    _HELD.pid = pid
    if key in held:
        yield
        return
    with AdvisoryLock(path.with_name(path.name + ".journal.lock"), timeout=5):
        _HELD.paths = held | {key}
        try:
            yield
        finally:
            _HELD.paths = held


def segment_paths(path: Path) -> list[Path]:
    directory = segment_directory(path)
    if not directory.is_dir() or directory.is_symlink():
        return []
    # A compression crash can leave both variants. The published gzip is
    # authoritative; never replay the same rows twice.
    paths = {
        p.name: p
        for p in directory.iterdir()
        if _SEGMENT.fullmatch(p.name) and p.is_file() and not p.is_symlink()
    }
    return [
        p
        for name, p in sorted(paths.items(), key=lambda pair: (int(pair[0].split(".")[1]), pair[0]))
        if (name + ".gz") not in paths
    ]


def has_segments(path: Path) -> bool:
    return segment_directory(path).is_dir()


@contextmanager
def head_read_lock(path: Path):
    """Fence indexed head reads; release before streaming immutable history."""
    if not path.with_name(path.name + ".rotation.json").exists() and not has_segments(path):
        yield
        return
    with journal_lock(path):
        if not has_segments(path):
            yield
            return
    yield


@lru_cache(maxsize=256)
def _rotation_state(path: Path, inode: int, modified: int, changed: int, size: int):
    # Stamped under the journal fence: external edits and atomic replacement
    # invalidate the bounded cache, while hot appends avoid reopening JSON.
    state = json.loads(path.read_text(encoding="utf-8"))
    return (state["utc-day"], state.get("segment-sequence", 0), state.get("last-event-sequence", 0))


def journal_sequence_watermark(path: Path) -> int:
    """Keep event IDs monotonic even after eligible raw history expires."""
    metadata = path.with_name(path.name + ".rotation.json")
    try:
        stamp = metadata.stat()
    except FileNotFoundError:
        return 0
    value = _rotation_state(
        metadata, stamp.st_ino, stamp.st_mtime_ns, stamp.st_ctime_ns, stamp.st_size
    )[2]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid journal event watermark")
    return value


def prepare_append(
    path: Path,
    index_path: Path,
    *,
    max_bytes: int,
    incoming_bytes: int = 0,
    now: datetime | None = None,
) -> bool:
    """Roll a nonempty head on UTC day/size boundaries; caller holds lock.

    Existing unsegmented heads are adopted using their mtime. Oversized
    single records stay intact; the next append starts another segment.
    """
    from audiagentic.foundation.io import atomic_write_json, tail_ndjson

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    try:
        head = path.lstat()
    except FileNotFoundError:
        head = None
    if head is not None and stat.S_ISLNK(head.st_mode):
        raise ValueError("journal head cannot be a symlink")
    day = now.date().isoformat()
    metadata = path.with_name(path.name + ".rotation.json")
    size = head.st_size if head is not None else 0
    try:
        stamp = metadata.stat()
    except FileNotFoundError:
        stamp = None
    if stamp is not None:
        opened_day, sequence, watermark = _rotation_state(
            metadata, stamp.st_ino, stamp.st_mtime_ns, stamp.st_ctime_ns, stamp.st_size
        )
    elif size:
        opened_day = datetime.fromtimestamp(head.st_mtime, timezone.utc).date().isoformat()
        sequence = 0
        watermark = 0
    else:
        opened_day = day
        sequence = 0
        watermark = 0
    if not isinstance(opened_day, str) or date.fromisoformat(opened_day).isoformat() != opened_day:
        raise ValueError("invalid journal rotation day")
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise ValueError("invalid journal segment sequence")
    rotated = bool(size and (opened_day != day or size + incoming_bytes > max_bytes))
    if rotated or not size:
        sequence = max([sequence, *[int(p.name.split(".")[1]) for p in segment_paths(path)]])
        rows = tail_ndjson(path, 1, _segments=False) if size else tail_segment_rows(path, 1)
        if rows:
            for key in ("event_seq", "event-seq"):
                value = rows[-1].get(key)
                if isinstance(value, int) and not isinstance(value, bool):
                    watermark = max(watermark, value)
    if rotated:
        directory = segment_directory(path)
        if directory.is_symlink():
            raise ValueError("journal segment directory cannot be a symlink")
        directory.mkdir(parents=True, exist_ok=True)
        sequence += 1
        if sequence >= 10**20:
            raise ValueError("journal segment sequence exhausted")
        destination = directory / f"{opened_day}.{sequence:020d}.{uuid.uuid4().hex}.ndjson"
        os.replace(path, destination)
        # Closed segments are streamed, not seeked using the head's index.
        index_path.unlink(missing_ok=True)
    elif not size:
        # Repair interruption after the head rename, before index removal.
        index_path.unlink(missing_ok=True)
    if rotated or not size or stamp is None or opened_day != day:
        atomic_write_json(
            metadata,
            {"utc-day": day, "segment-sequence": sequence, "last-event-sequence": watermark},
        )
    return rotated


def iter_segment_rows(path: Path):
    """Read closed plain/gzip segments followed by the current head."""
    # Snapshot the bounded active head under the rotation fence. Archives are
    # immutable; a later rollover cannot make this read skip or duplicate it.
    with journal_lock(path):
        sources = segment_paths(path)
        head = path.read_bytes() if path.exists() else b""
    for source in sources:
        try:
            stream = (
                gzip.open(source, "rt", encoding="utf-8")
                if source.suffix == ".gz"
                else source.open(encoding="utf-8")
            )
        except FileNotFoundError:
            # Compression publishes before removing the source.
            compressed = source.with_name(source.name + ".gz")
            if not compressed.exists():
                continue
            stream = gzip.open(compressed, "rt", encoding="utf-8")
        with stream:
            for line in stream:
                if line.strip():
                    row = json.loads(line)
                    if isinstance(row, dict):
                        yield row
    for line in head.splitlines():
        if line.strip():
            row = json.loads(line)
            if isinstance(row, dict):
                yield row


def tail_segment_rows(path: Path, limit: int) -> list[dict]:
    """Bound memory while reading backwards by segment (not all history)."""
    from audiagentic.foundation.io import tail_ndjson

    with journal_lock(path):
        result = tail_ndjson(path, limit, _segments=False)
        sources = segment_paths(path)
    for source in reversed(sources):
        if len(result) >= limit:
            break
        opener = gzip.open if source.suffix == ".gz" else open
        try:
            with opener(source, "rt", encoding="utf-8") as stream:
                rows = deque(maxlen=limit - len(result))
                for line in stream:
                    if line.strip():
                        row = json.loads(line)
                        if isinstance(row, dict):
                            rows.append(row)
            result = list(rows) + result
        except FileNotFoundError:
            compressed = source.with_name(source.name + ".gz")
            if compressed.exists():
                with gzip.open(compressed, "rt", encoding="utf-8") as stream:
                    rows = deque(
                        (json.loads(line) for line in stream if line.strip()),
                        maxlen=limit - len(result),
                    )
                result = [row for row in rows if isinstance(row, dict)] + result
    return result


def _journal_content(rows: list[dict[str, Any]]) -> tuple[bytes, bytes]:
    journal = bytearray()
    index = bytearray()
    for row in rows:
        line = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        offset = len(journal)
        journal.extend(line)
        metadata: dict[str, Any] = {"offset": offset, "length": len(line)}
        if "event_seq" in row:
            metadata["event_seq"] = row["event_seq"]
        if "event-seq" in row:
            metadata["event-seq"] = row["event-seq"]
        index.extend(
            (json.dumps(metadata, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        )
    return bytes(journal), bytes(index)


def compact_indexed_ndjson(
    journal_path: Path,
    index_path: Path,
    *,
    max_bytes: int,
    preserve: Callable[[dict[str, Any]], bool] | None = None,
) -> bool:
    """Compact a non-segmented indexed journal, preserving required evidence."""
    from audiagentic.foundation.io import atomic_write_bytes, iter_ndjson

    if not journal_path.exists() or journal_path.stat().st_size <= max_bytes:
        return False
    try:
        rows = list(iter_ndjson(journal_path, _segments=False))
    except (OSError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        logger.warning(
            "indexed journal compaction skipped for unreadable journal",
            extra={"path": str(journal_path)},
        )
        return False
    if not rows:
        return False
    preserve = preserve or (lambda row: False)
    must_keep = {index for index, row in enumerate(rows) if preserve(row)}
    must_keep.add(len(rows) - 1)
    encoded = [
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    ]

    selected = set(must_keep)
    selected_bytes = sum(len(encoded[index]) for index in selected)
    if selected_bytes <= max_bytes:
        # Leave headroom so the next append does not immediately rewrite
        # both files again. Required evidence is never dropped for headroom.
        target_bytes = max(selected_bytes, max_bytes * 3 // 4)
        for index in range(len(rows) - 1, -1, -1):
            if index in selected:
                continue
            row_bytes = len(encoded[index])
            if selected_bytes + row_bytes > target_bytes:
                break
            selected.add(index)
            selected_bytes += row_bytes
    else:
        # A single terminal row is irreducible evidence. Keep the newest
        # terminal row even if an operator configured a cap smaller than it.
        selected = {len(rows) - 1}
    kept = [rows[index] for index in sorted(selected)]
    journal, index = _journal_content(kept)
    atomic_write_bytes(journal_path, journal)
    atomic_write_bytes(index_path, index)
    return True


def maintain_segments(
    path: Path, *, delete_before: float | None, max_operations: int = 100, compress: bool = True
) -> dict[str, int]:
    # Multiple compressors must not race on Windows plain-file handles.
    # This lock is separate from the append writer's journal fence.
    with StartupLock(path.with_name(path.name + ".maintenance.lock"), timeout=5):
        return _maintain_segments(
            path, delete_before=delete_before, max_operations=max_operations, compress=compress
        )


def _maintain_segments(
    path: Path, *, delete_before: float | None, max_operations: int, compress: bool
) -> dict[str, int]:
    """Maintain only recognized closed segments; never touch current heads.

    Callers retain their eligibility fence during deletion. Compression is
    lossless and runs outside the writer fence; only publication is locked.
    A resource maintenance fence must prevent concurrent explicit purge.
    """
    result = {"compressed": 0, "deleted": 0, "temporary-deleted": 0}
    # The dedicated maintenance lock proves no compressor is using these
    # private, non-authoritative temporary copies after a process crash.
    directory = segment_directory(path)
    if directory.is_dir() and not directory.is_symlink():
        for temporary in directory.iterdir():
            if sum(result.values()) >= max_operations:
                return result
            if (
                re.fullmatch(r"\.compress-[a-z0-9_]{8}", temporary.name)
                and temporary.is_file()
                and not temporary.is_symlink()
            ):
                temporary.unlink()
                result["temporary-deleted"] += 1
    with journal_lock(path):
        sources = segment_paths(path)
    for source in sources:
        if sum(result.values()) >= max_operations:
            break
        with journal_lock(path):
            if not source.exists():
                continue
            stat = source.stat()
            if delete_before is not None and stat.st_mtime <= delete_before:
                if source.suffix == ".gz":
                    source.with_suffix("").unlink(missing_ok=True)
                source.unlink()
                result["deleted"] += 1
                continue
        if not compress or source.suffix == ".gz":
            if compress and source.suffix == ".gz":
                try:
                    source.with_suffix("").unlink(missing_ok=True)
                except PermissionError:
                    pass  # A reader still holds the plain file; retry later.
            continue
        target = source.with_name(source.name + ".gz")
        fd, temporary = tempfile.mkstemp(prefix=".compress-", dir=source.parent)
        try:
            with os.fdopen(fd, "wb") as raw:
                with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
                    with source.open("rb") as original:
                        shutil.copyfileobj(original, zipped)
                raw.flush()
                os.fsync(raw.fileno())
            os.utime(temporary, (stat.st_atime, stat.st_mtime))
            with journal_lock(path):
                if source.exists():
                    os.replace(temporary, target)
                    try:
                        source.unlink()
                    except PermissionError:
                        pass  # Published gzip is valid; defer plain cleanup.
                    result["compressed"] += 1
        finally:
            Path(temporary).unlink(missing_ok=True)
    return result
