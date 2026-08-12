"""Durable operation store for SH24 gateway operations.

The store is an operation outbox.  A notifier may lose, duplicate, or reorder
wake-ups because a pump always rereads this store and claims with a durable
revision/owner fence before executing any effect.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json, read_text_with_retry
from audiagentic.foundation.observability import record_timeline_event
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z
from audiagentic.foundation.workflow import load_workflow, states_in_set, transition_allowed

from .contracts import ManagementCommand

_WORKFLOW = load_workflow(Path(__file__).parent.parent.parent / "workflows.yaml", "gateway-operation")
_DISPATCHABLE = frozenset(states_in_set(_WORKFLOW, "dispatchable"))
_TERMINAL = frozenset(states_in_set(_WORKFLOW, "terminal"))
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,127}$")
_FORBIDDEN_SCOPE_KEYS = frozenset(
    {
        "prompt",
        "prompt-body",
        "prompt_body",
        "output",
        "raw-output",
        "raw_output",
        "credential",
        "credentials",
        "token",
        "password",
        "authorization",
    }
)


class ManagementOperationStore:
    """File-backed durable authority for management operation lifecycle."""

    def __init__(self, service_root: Path) -> None:
        self._root = service_root / "gateway-operations"

    @property
    def root(self) -> Path:
        return self._root

    def create(self, command: ManagementCommand) -> dict[str, Any]:
        """Create accepted work, or return the same operation idempotently."""
        operation_id = _require_id(command.operation_id)
        scope = _validate_scope(command.scope)
        intent = {
            "kind": command.kind.value,
            "scope": scope,
            "correlation-id": command.correlation_id,
        }
        digest = _intent_digest(intent)
        with self._lock(operation_id):
            path = self._record_path(operation_id)
            if path.exists():
                existing = self._read_unlocked(operation_id)
                if existing["intent-digest"] != digest:
                    raise AudiaGenticError(
                        "CON-AGM-001",
                        "agents",
                        "gateway operation id conflicts with existing intent",
                        {"operation-id": operation_id},
                    )
                return existing
            timestamp = now_iso_z()
            record = {
                "contract-version": "v1",
                "operation-id": operation_id,
                "kind": command.kind.value,
                "scope": scope,
                "intent-digest": digest,
                "correlation-id": command.correlation_id,
                "state": "accepted",
                "revision": 0,
                "owner-epoch": None,
                "created-at": timestamp,
                "updated-at": timestamp,
                "started-at": None,
                "finished-at": None,
                "result": None,
                "error": None,
            }
            self._write_unlocked(record)
        self._timeline(record, "gateway.operation-created")
        return record

    def read(self, operation_id: str) -> dict[str, Any]:
        operation_id = _require_id(operation_id)
        with self._lock(operation_id):
            return self._read_unlocked(operation_id)

    def list_dispatchable(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if limit <= 0:
            raise AudiaGenticError("VAL-AGM-001", "agents", "limit must be positive", {})
        if not self._root.exists():
            return []
        records: list[dict[str, Any]] = []
        for child in sorted(self._root.iterdir()):
            if not child.is_dir() or not _ID_RE.fullmatch(child.name):
                continue
            try:
                record = self.read(child.name)
            except AudiaGenticError:
                continue
            if record["state"] in _DISPATCHABLE:
                records.append(record)
            if len(records) >= limit:
                break
        return records

    def list_records(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """List durable operator records newest first for safe inspection."""
        if limit <= 0:
            raise AudiaGenticError("VAL-AGM-001", "agents", "limit must be positive", {})
        if not self._root.exists():
            return []
        records: list[dict[str, Any]] = []
        for child in self._root.iterdir():
            if not child.is_dir() or not _ID_RE.fullmatch(child.name):
                continue
            try:
                records.append(self.read(child.name))
            except AudiaGenticError:
                continue
        records.sort(key=lambda item: str(item.get("created-at", "")), reverse=True)
        return records[:limit]

    def active_count(self) -> int:
        """Return accepted/running gateway-operation count for quiescence."""
        if not self._root.exists():
            return 0
        count = 0
        for child in self._root.iterdir():
            if not child.is_dir() or not _ID_RE.fullmatch(child.name):
                continue
            try:
                state = self.read(child.name)["state"]
            except AudiaGenticError:
                continue
            if state in {"accepted", "running"}:
                count += 1
        return count

    def recover_prior_owner_claims(self, *, owner_epoch: str) -> int:
        """Return claims from a superseded service owner to dispatchable work.

        The caller is the newly claimed single service authority.  This is not
        a timeout inference: ownership is fenced by the managed service epoch.
        """
        if not owner_epoch or not self._root.exists():
            return 0
        recovered = 0
        for child in sorted(self._root.iterdir()):
            if not child.is_dir() or not _ID_RE.fullmatch(child.name):
                continue
            with self._lock(child.name):
                record = self._read_unlocked(child.name)
                if record["state"] != "running" or record.get("owner-epoch") == owner_epoch:
                    continue
                updated = self._transition(record, "accepted")
                updated["owner-epoch"] = None
                updated["started-at"] = None
                self._write_unlocked(updated)
            self._timeline(updated, "gateway.operation-requeued-after-owner-change")
            recovered += 1
        return recovered

    def claim(self, operation_id: str, *, owner_epoch: str) -> dict[str, Any] | None:
        """CAS claim accepted work.  A duplicate claimant gets ``None``."""
        operation_id = _require_id(operation_id)
        if not owner_epoch:
            raise AudiaGenticError("VAL-AGM-002", "agents", "owner epoch is required", {})
        with self._lock(operation_id):
            record = self._read_unlocked(operation_id)
            if record["state"] not in _DISPATCHABLE:
                return None
            updated = self._transition(record, "running")
            updated["owner-epoch"] = owner_epoch
            updated["started-at"] = now_iso_z()
            self._write_unlocked(updated)
        self._timeline(updated, "gateway.operation-claimed")
        return updated

    def finish(
        self,
        operation_id: str,
        *,
        owner_epoch: str,
        result: Mapping[str, Any] | None = None,
        error: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Finish a claimed operation, fenced by its owner epoch."""
        operation_id = _require_id(operation_id)
        with self._lock(operation_id):
            record = self._read_unlocked(operation_id)
            if record["state"] != "running" or record.get("owner-epoch") != owner_epoch:
                raise AudiaGenticError(
                    "CON-AGM-002", "agents", "gateway operation ownership changed", {}
                )
            final_state = "failed" if error else "completed"
            updated = self._transition(record, final_state)
            updated["result"] = _validate_result(result or {}) if not error else None
            updated["error"] = _validate_error(error) if error else None
            updated["finished-at"] = now_iso_z()
            self._write_unlocked(updated)
        self._timeline(updated, f"gateway.operation-{updated['state']}")
        return updated

    def fail(self, operation_id: str, *, owner_epoch: str, code: str) -> dict[str, Any]:
        """Record a bounded operational failure without exception text."""
        return self.finish(operation_id, owner_epoch=owner_epoch, error={"code": code})

    def _record_path(self, operation_id: str) -> Path:
        return self._root / operation_id / "record.json"

    def _timeline_path(self, operation_id: str) -> Path:
        return self._root / operation_id / "timeline.ndjson"

    def _lock(self, operation_id: str) -> StartupLock:
        return StartupLock(self._root / operation_id / "mutation.lock")

    def _read_unlocked(self, operation_id: str) -> dict[str, Any]:
        try:
            raw = json.loads(read_text_with_retry(self._record_path(operation_id)))
        except OSError as exc:
            raise AudiaGenticError(
                "RES-AGM-001", "agents", "gateway operation not found", {"operation-id": operation_id}
            ) from exc
        except ValueError as exc:
            raise AudiaGenticError(
                "IO-AGM-001", "agents", "gateway operation record is invalid", {}
            ) from exc
        if not isinstance(raw, dict):
            raise AudiaGenticError("IO-AGM-001", "agents", "gateway operation record is invalid", {})
        _validate_record(raw)
        return raw

    def _write_unlocked(self, record: Mapping[str, Any]) -> None:
        _validate_record(record)
        atomic_write_json(self._record_path(str(record["operation-id"])), dict(record))

    def _transition(self, record: Mapping[str, Any], new_state: str) -> dict[str, Any]:
        old_state = str(record["state"])
        if not transition_allowed(_WORKFLOW, old_state, new_state):
            raise AudiaGenticError(
                "CON-AGM-003",
                "agents",
                "undeclared gateway operation transition",
                {"from": old_state, "to": new_state},
            )
        updated = dict(record)
        updated["state"] = new_state
        updated["revision"] = int(record["revision"]) + 1
        updated["updated-at"] = now_iso_z()
        return updated

    def _timeline(self, record: Mapping[str, Any], event: str) -> None:
        record_timeline_event(
            self._timeline_path(str(record["operation-id"])),
            component="agents",
            resource_kind="gateway-operation",
            resource_id=str(record["operation-id"]),
            event=event,
            state=str(record["state"]),
            attributes={"kind": record["kind"], "revision": record["revision"]},
            correlation_id=record.get("correlation-id"),
        )


def _require_id(operation_id: str) -> str:
    if not _ID_RE.fullmatch(operation_id):
        raise AudiaGenticError("VAL-AGM-003", "agents", "operation id is invalid", {})
    return operation_id


def _intent_digest(intent: Mapping[str, Any]) -> str:
    payload = json.dumps(intent, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_scope(scope: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(scope, Mapping):
        raise AudiaGenticError("VAL-AGM-004", "agents", "gateway operation scope must be a mapping", {})
    normalized = _safe_value(dict(scope))
    if not isinstance(normalized, dict):  # defensive; _safe_value preserves mappings
        raise AudiaGenticError("VAL-AGM-004", "agents", "gateway operation scope must be a mapping", {})
    return normalized


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str) or raw_key.lower() in _FORBIDDEN_SCOPE_KEYS:
                raise AudiaGenticError("VAL-AGM-005", "agents", "gateway operation scope contains forbidden data", {})
            normalized[raw_key] = _safe_value(raw_value)
        return normalized
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    raise AudiaGenticError("VAL-AGM-005", "agents", "gateway operation scope must be JSON data", {})


def _validate_result(result: Mapping[str, Any]) -> dict[str, Any]:
    return _validate_scope(result)


def _validate_error(error: Mapping[str, Any]) -> dict[str, Any]:
    if set(error) != {"code"} or not isinstance(error.get("code"), str) or not error["code"]:
        raise AudiaGenticError("VAL-AGM-006", "agents", "gateway operation error must contain only code", {})
    return {"code": error["code"]}


def _validate_record(record: Mapping[str, Any]) -> None:
    required = {
        "contract-version", "operation-id", "kind", "scope", "intent-digest", "correlation-id", "state",
        "revision", "owner-epoch", "created-at", "updated-at", "started-at", "finished-at", "result", "error",
    }
    if set(record) != required or record.get("contract-version") != "v1":
        raise AudiaGenticError("VAL-AGM-007", "agents", "gateway operation record is invalid", {})
    _require_id(str(record.get("operation-id", "")))
    if record.get("state") not in {"accepted", "running", *_TERMINAL}:
        raise AudiaGenticError("VAL-AGM-007", "agents", "gateway operation record is invalid", {})
    if not isinstance(record.get("revision"), int) or int(record["revision"]) < 0:
        raise AudiaGenticError("VAL-AGM-007", "agents", "gateway operation record is invalid", {})
    _validate_scope(record.get("scope", {}))
    if record.get("result") is not None:
        _validate_result(record["result"])
    if record.get("error") is not None:
        _validate_error(record["error"])


__all__ = ["ManagementOperationStore"]
