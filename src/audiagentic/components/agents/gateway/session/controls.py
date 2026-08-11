"""Durable idempotency for closed generic session controls (AS95)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audiagentic.components.agents.agents_paths import (
    gateway_session_control_idempotency_path,
    gateway_session_control_lock_path,
)
from audiagentic.components.agents.gateway.store import hash_idempotency_key
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.system.process import StartupLock
from audiagentic.foundation.time import now_iso_z


def _fingerprint(*, session_id: str, turn_id: str | None, action: str, payload: dict[str, Any]) -> str:
    raw = json.dumps(
        {"session-id": session_id, "turn-id": turn_id, "action": action, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hash_idempotency_key(raw)


def execute_once(
    project_root: Path,
    *,
    session_id: str,
    turn_id: str | None,
    action: str,
    control_id: str,
    payload: dict[str, Any],
    dispatch: Any,
) -> dict[str, Any]:
    """Dispatch once per control id, rejecting reuse with a different target."""
    path = gateway_session_control_idempotency_path(project_root, session_id)
    fingerprint = _fingerprint(session_id=session_id, turn_id=turn_id, action=action, payload=payload)
    with StartupLock(gateway_session_control_lock_path(project_root, session_id)):
        data: dict[str, Any] = {"contract-version": "v1", "entries": {}}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and isinstance(loaded.get("entries"), dict):
                    data = loaded
            except (OSError, ValueError):
                pass
        key = hash_idempotency_key(control_id)
        prior = data["entries"].get(key)
        if isinstance(prior, dict):
            if prior.get("fingerprint") != fingerprint:
                raise AudiaGenticError(
                    code="CON-AGW-131",
                    kind="agents",
                    message="session control id was reused for a different target",
                    details={"session-id": session_id},
                )
            return dict(prior.get("result") or {})
        result = dict(dispatch())
        data["entries"][key] = {
            "fingerprint": fingerprint,
            "result": result,
            "recorded-at": now_iso_z(),
        }
        atomic_write_json(path, data)
        return result
