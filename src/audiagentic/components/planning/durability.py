"""Recoverable local transactions for multi-file planning mutations.

The planning backend is a collection of Markdown files rather than a database.
This module supplies a small roll-forward journal so a process failure between
writing a destination and removing a source can be repaired on the next use.
It intentionally promises local, at-least-once recovery only; it does not try
to emulate database transactions or claim stronger filesystem guarantees than
``os.replace`` and file fsync provide on the host platform.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from audiagentic.components.planning.contracts import PlanningIntegrityError
from audiagentic.foundation.io import atomic_write_bytes, atomic_write_json
from audiagentic.foundation.paths.safety import resolve_user_path
from audiagentic.foundation.system.process import StartupLock

_JOURNAL_DIR = ".audiagentic/runtime/planning"
_TXNS_DIR = "txns"
_LEGACY_TXN_DIR_RE = re.compile(r"^[0-9a-f]{32}$")


def journal_root(project_root: Path) -> Path:
    return resolve_user_path(_JOURNAL_DIR, project_root=project_root, field_name="Planning journal")


def transaction_root(project_root: Path) -> Path:
    return resolve_user_path(
        Path(_JOURNAL_DIR) / _TXNS_DIR,
        project_root=project_root,
        field_name="Planning transaction journal",
    )


def _journal_lock(project_root: Path) -> StartupLock:
    return StartupLock(journal_root(project_root) / "journal.lock", timeout=30.0)


def _resolved(root: Path, path: Path) -> Path:
    root_resolved = root.resolve(strict=False)
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PlanningIntegrityError(f"transaction path escapes project root: {path}") from exc
    return resolved


def _relative(root: Path, path: Path) -> str:
    return _resolved(root, path).relative_to(root.resolve(strict=False)).as_posix()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _durable_json(path: Path, value: Any) -> None:
    atomic_write_json(path, value)
    try:
        with path.open("rb") as handle:
            os.fsync(handle.fileno())
    except OSError:
        # The atomic write is still the strongest portable guarantee available
        # on some Windows filesystems; recovery remains idempotent.
        pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PlanningIntegrityError(f"invalid planning transaction manifest: {path}") from exc
    if not isinstance(value, dict):
        raise PlanningIntegrityError(f"planning transaction manifest is not an object: {path}")
    return value


def _apply_write(root: Path, tx_dir: Path, intent: Mapping[str, Any]) -> None:
    relative = intent.get("relative-path")
    payload_name = intent.get("payload")
    expected = intent.get("sha256")
    previous = intent.get("previous-sha256")
    if not isinstance(relative, str) or not isinstance(payload_name, str) or not isinstance(expected, str):
        raise PlanningIntegrityError("malformed planning write intent")
    target = _resolved(root, root / relative)
    payload_path = _resolved(tx_dir, tx_dir / payload_name)
    if payload_path.parent != tx_dir.resolve(strict=False):
        raise PlanningIntegrityError("planning transaction payload escapes transaction directory")
    try:
        data = payload_path.read_bytes()
    except OSError as exc:
        raise PlanningIntegrityError(f"planning transaction payload is missing: {payload_name}") from exc
    if _sha256(data) != expected:
        raise PlanningIntegrityError(f"planning transaction payload hash mismatch: {relative}")
    if target.exists():
        try:
            current = _sha256(target.read_bytes())
            if current == expected:
                return
            if isinstance(previous, str) and current == previous:
                atomic_write_bytes(target, data)
                return
        except OSError as exc:
            raise PlanningIntegrityError(f"cannot inspect planning transaction target: {target}") from exc
        raise PlanningIntegrityError(f"unexpected existing planning transaction target: {target}")
    atomic_write_bytes(target, data)


def _apply_delete(root: Path, intent: Mapping[str, Any]) -> None:
    relative = intent.get("relative-path")
    expected = intent.get("sha256")
    if not isinstance(relative, str):
        raise PlanningIntegrityError("malformed planning delete intent")
    target = _resolved(root, root / relative)
    if not target.exists():
        return
    if expected is not None:
        if not isinstance(expected, str) or _sha256(target.read_bytes()) != expected:
            raise PlanningIntegrityError(f"unexpected existing planning delete target: {target}")
    try:
        target.unlink()
    except OSError as exc:
        raise PlanningIntegrityError(f"cannot remove planning transaction source: {target}") from exc


def _apply_manifest(project_root: Path, tx_dir: Path, manifest: Mapping[str, Any]) -> None:
    if manifest.get("version") != 1:
        raise PlanningIntegrityError("unsupported planning transaction version")
    writes = manifest.get("writes", [])
    deletes = manifest.get("deletes", [])
    if not isinstance(writes, list) or not isinstance(deletes, list):
        raise PlanningIntegrityError("malformed planning transaction intents")
    for intent in writes:
        if not isinstance(intent, Mapping):
            raise PlanningIntegrityError("malformed planning write intent")
        _apply_write(project_root, tx_dir, intent)
    for intent in deletes:
        if not isinstance(intent, Mapping):
            raise PlanningIntegrityError("malformed planning delete intent")
        _apply_delete(project_root, intent)


def _persist_event_from_manifest(project_root: Path, manifest: Mapping[str, Any]) -> None:
    event = manifest.get("planning-event")
    if not event:
        return
    if not isinstance(event, Mapping):
        raise PlanningIntegrityError("malformed planning event intent")
    from audiagentic.components.planning.events import enqueue_planning_event

    enqueue_planning_event(
        project_root,
        str(event.get("event-type", "")),
        dict(event.get("payload") or {}),
        metadata=dict(event.get("metadata") or {}),
        event_id=str(event.get("event-id")) if event.get("event-id") else None,
    )


def reconcile_pending_mutations(project_root: Path) -> int:
    """Roll forward all prepared transactions; return the count repaired."""
    with _journal_lock(project_root):
        return _reconcile_pending_mutations(project_root)


def _reconcile_pending_mutations(project_root: Path) -> int:
    """Roll forward pending transactions while the journal lock is held."""
    root = transaction_root(project_root)
    if not root.exists():
        return 0
    repaired = 0
    for tx_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        manifest_path = tx_dir / "manifest.json"
        # Payloads are staged before the manifest is durable.  A process
        # failure in that window must not turn an incomplete staging directory
        # into a fatal recovery error or expose it as a transaction.  Once the
        # manifest exists, the directory is a valid roll-forward candidate.
        if not manifest_path.exists() and (
            tx_dir.name.startswith(".staging-") or _LEGACY_TXN_DIR_RE.fullmatch(tx_dir.name)
        ):
            shutil.rmtree(tx_dir)
            continue
        manifest = _read_json(manifest_path)
        _apply_manifest(project_root, tx_dir, manifest)
        _persist_event_from_manifest(project_root, manifest)
        _durable_json(tx_dir / "manifest.json", {**manifest, "phase": "committed"})
        shutil.rmtree(tx_dir)
        repaired += 1
    return repaired


def commit_mutation(
    project_root: Path,
    writes: Mapping[Path, str | bytes],
    deletes: Iterable[Path] = (),
    *,
    operation: str,
    planning_event: Mapping[str, Any] | None = None,
) -> str:
    """Durably apply a set of writes/deletes and return its transaction ID."""
    with _journal_lock(project_root):
        _reconcile_pending_mutations(project_root)
        tx_id = uuid.uuid4().hex
        tx_dir = transaction_root(project_root) / f".staging-{tx_id}"
        tx_dir.mkdir(parents=True, exist_ok=False)
        write_intents: list[dict[str, Any]] = []
        for index, (path, content) in enumerate(writes.items()):
            data = content.encode("utf-8") if isinstance(content, str) else bytes(content)
            payload_name = f"write-{index:03d}.payload"
            atomic_write_bytes(tx_dir / payload_name, data)
            resolved_path = _resolved(project_root, path)
            previous = _sha256(resolved_path.read_bytes()) if resolved_path.exists() else None
            write_intents.append(
                {
                    "relative-path": _relative(project_root, path),
                    "payload": payload_name,
                    "sha256": _sha256(data),
                    "previous-sha256": previous,
                }
            )
        delete_intents: list[dict[str, Any]] = []
        for path in deletes:
            resolved = _resolved(project_root, path)
            expected = _sha256(resolved.read_bytes()) if resolved.exists() else None
            delete_intents.append({"relative-path": _relative(project_root, resolved), "sha256": expected})
        manifest: dict[str, Any] = {
            "version": 1,
            "mutation-id": tx_id,
            "operation": operation,
            "phase": "prepared",
            "writes": write_intents,
            "deletes": delete_intents,
        }
        if planning_event is not None:
            manifest["planning-event"] = dict(planning_event)
        _durable_json(tx_dir / "manifest.json", manifest)
        try:
            _apply_manifest(project_root, tx_dir, manifest)
            _persist_event_from_manifest(project_root, manifest)
            _durable_json(tx_dir / "manifest.json", {**manifest, "phase": "committed"})
            shutil.rmtree(tx_dir)
        except Exception:
            # Leave the prepared transaction for a later first-use reconciliation.
            raise
        return tx_id


__all__ = ["commit_mutation", "journal_root", "reconcile_pending_mutations", "transaction_root"]
