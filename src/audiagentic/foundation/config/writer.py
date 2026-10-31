"""Write settings: the one place that edits a settings file.

``write_settings_patch`` applies an RFC 7396 patch to one scope's file. It edits
the file's text so comments and order survive (``yaml_edit``), parses the
candidate with the same strict loader and schema the resolver uses, and writes
only when that candidate is exactly ``merged(old, patch)``. Writers are
serialized by a lock held outside the repository, the file is re-read just
before it is replaced so a human edit in the meantime is refused rather than
overwritten, and the previous content is kept as a bounded backup.
"""
from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from audiagentic.foundation.io import atomic_write_bytes
from audiagentic.foundation.paths.home import user_state_dir
from audiagentic.foundation.system.advisory_lock import AdvisoryLock

from .merge import merged
from .settings import SETTINGS_FILE, document_issues, raise_issues, scope_sources, section_scopes
from .strict_yaml import load_settings_text, settings_error
from .yaml_edit import patch_text

WRITABLE_SCOPES = ("user", "user-project", "project")
BACKUPS_KEPT = 5
_NEW_FILE = "schema_version: 1\n"
_SHARED_FILE_MODE = 0o644
_PRIVATE_FILE_MODE = 0o600


@dataclass(frozen=True)
class WriteResult:
    path: Path
    scope: str
    changed: bool
    written: bool
    keys: tuple[str, ...]  # dotted keys whose value in this file changed
    diff: str
    backup: Path | None


def write_settings_patch(
    scope: str, patch: dict[str, Any], *, project_root: Path | None = None, dry_run: bool = False,
) -> WriteResult:
    path = _target(scope, project_root)
    _check_sections(scope, patch)
    with AdvisoryLock(_state_file("locks", path, ".lock")):
        raw = path.read_bytes() if path.is_file() else None
        old_text = raw.decode("utf-8-sig") if raw is not None else _NEW_FILE
        old = load_settings_text(old_text, path).data
        new = merged(old, patch)
        keys = tuple(_changed_keys(old, new))
        if not keys:
            return WriteResult(path, scope, False, False, (), "", None)
        text = patch_text(old_text, old, patch)
        candidate = load_settings_text(text, path)
        if candidate.data != new:
            raise settings_error(12, "Settings file layout cannot be edited safely", file=str(path))
        issues = document_issues(candidate)
        if issues:
            raise_issues(issues)
        diff = "".join(difflib.unified_diff(
            old_text.splitlines(keepends=True), text.splitlines(keepends=True), str(path), str(path) + " (new)",
        ))
        if dry_run:
            return WriteResult(path, scope, True, False, keys, diff, None)
        current = path.read_bytes() if path.is_file() else None
        if _digest(current) != _digest(raw):
            raise settings_error(11, "Settings file changed while the write was prepared", file=str(path))
        backup = _backup(path, raw) if raw is not None else None
        atomic_write_bytes(path, text.encode("utf-8"), mode=_mode(scope, path))
    return WriteResult(path, scope, True, True, keys, diff, backup)


def read_scope_settings(scope: str, *, project_root: Path | None = None) -> dict[str, Any]:
    """The values written in one scope's own file (not the effective merge); ``{}`` if absent.

    For read-modify-write cycles that must not copy another scope's values into this one.
    """
    path = _target(scope, project_root)
    if not path.is_file():
        return {}
    return load_settings_text(path.read_text(encoding="utf-8-sig"), path).data


def replacement_patch(old: Any, new: Any) -> Any:
    """An RFC 7396 patch that turns ``old`` into exactly ``new`` (``null`` removes what ``new`` drops)."""
    if isinstance(old, dict) and isinstance(new, dict):
        patch: dict[str, Any] = {key: None for key in old.keys() - new.keys()}
        for key, value in new.items():
            if key not in old:
                patch[key] = value
            elif old[key] != value:
                patch[key] = replacement_patch(old[key], value)
        return patch
    return new


def replace_section(
    scope: str, section: str, value: dict[str, Any], *, project_root: Path | None = None,
) -> WriteResult:
    """Make one scope's ``section`` exactly ``value`` (an empty mapping removes it)."""
    return replace_at(scope, (section,), value, project_root=project_root)


def replace_at(
    scope: str, path: tuple[str, ...], value: dict[str, Any], *, project_root: Path | None = None,
) -> WriteResult:
    """Make the mapping at ``path`` in one scope's file exactly ``value`` (empty removes it)."""
    node: Any = read_scope_settings(scope, project_root=project_root)
    for part in path:
        node = node.get(part) if isinstance(node, dict) else None
    old = node
    if not value:
        change: Any = None if old is not None else {}
    else:
        change = replacement_patch(old if isinstance(old, dict) else {}, value)
    patch_doc: dict[str, Any] = {}
    if change != {} or old is not None:
        patch_doc = change
        for part in reversed(path):
            patch_doc = {part: patch_doc}
    return write_settings_patch(scope, patch_doc, project_root=project_root)


def _target(scope: str, project_root: Path | None) -> Path:
    if scope not in WRITABLE_SCOPES:
        raise settings_error(8, "Settings scope cannot be written", scope=scope, writable=list(WRITABLE_SCOPES))
    source = next((s for s in scope_sources(project_root=project_root) if s.scope == scope), None)
    if source is None or source.path is None:
        raise settings_error(8, "Settings scope has no file here: run inside a project checkout", scope=scope)
    for unsafe in (source.path, source.path.parent):
        if unsafe.is_symlink():
            raise settings_error(10, "Settings target is a symbolic link", file=str(source.path), link=str(unsafe))
    return source.path


def _check_sections(scope: str, patch: dict[str, Any]) -> None:
    for section in patch:
        allowed = section_scopes(section)
        if allowed and scope not in allowed:
            raise settings_error(
                9, "Settings section is not read from this scope", section=section, scope=scope, allowed=list(allowed),
            )


def _changed_keys(old: Any, new: Any, prefix: str = "") -> list[str]:
    if isinstance(old, dict | None) and isinstance(new, dict | None) and (old or new):
        found: list[str] = []
        for name in sorted((old or {}).keys() | (new or {}).keys()):
            found += _changed_keys((old or {}).get(name), (new or {}).get(name), f"{prefix}{name}.")
        return found
    return [] if old == new else [prefix.rstrip(".")]


def _digest(raw: bytes | None) -> str | None:
    return None if raw is None else hashlib.sha256(raw).hexdigest()


def _state_file(kind: str, path: Path, suffix: str = "") -> Path:
    return user_state_dir() / kind / (hashlib.sha256(str(path).encode()).hexdigest()[:16] + suffix)


def _mode(scope: str, path: Path) -> int:
    if path.is_file():
        return path.stat().st_mode & 0o777
    return _PRIVATE_FILE_MODE if scope in ("user", "user-project") else _SHARED_FILE_MODE


def _backup(path: Path, raw: bytes) -> Path:
    directory = _state_file("settings-backups", path)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = directory / f"{stamp}-{_digest(raw)[:8]}-{SETTINGS_FILE}"
    atomic_write_bytes(target, raw, mode=_PRIVATE_FILE_MODE)
    for stale in sorted(directory.iterdir())[:-BACKUPS_KEPT]:
        stale.unlink(missing_ok=True)
    return target


__all__ = [
    "BACKUPS_KEPT", "WRITABLE_SCOPES", "WriteResult", "read_scope_settings", "replace_at", "replace_section",
    "replacement_patch", "write_settings_patch",
]
