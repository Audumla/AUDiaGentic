"""Fixtures for the session-purge tests: a project, closed sessions with an accepted-turn clock, and requests."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from audiagentic.components.agents.gateway import store
from audiagentic.components.agents.gateway.session import sessions_store
from tests.helpers.gateway_settings import use_gateway_settings

DAY = 86400.0


def enable_policy(monkeypatch, tmp_path, **retention):
    base = {"purge_enabled": False, "session_purge_enabled": True, "session_purge_inactivity_seconds": DAY}
    return use_gateway_settings(monkeypatch, tmp_path, retention={**base, **retention})


def iso_ago(delta_seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=delta_seconds)).isoformat().replace("+00:00", "Z")


def make_session(root: Path, *, state="closed", age=2 * DAY, requests=(), claim=None, clock=True):
    record = sessions_store.build_session_record(execution_profile_id="default")
    record["state"] = state
    timing = dict(record.get("timing") or {})
    if clock:
        timing["last-accepted-turn-at"] = iso_ago(age)
    else:
        timing.pop("last-accepted-turn-at", None)
    record["timing"] = timing
    record["activity"] = {**(record.get("activity") or {}), "request-ids": list(requests)}
    if claim:
        record["retention-claim"] = {"operation-id": claim, "claimed-at": iso_ago(0)}
    sessions_store.write_session_record(root, record)
    return record["session-id"]


def make_request(root: Path, session_id: str, state="completed") -> str:
    record = store.build_record(execution_profile_id="default", prompt_body="x", session_id=session_id)
    store.write_record(root, record)
    if state != "queued":
        store.transition_record(root, record["request-id"], "running")
        if state != "running":
            store.transition_record(root, record["request-id"], state)
    return record["request-id"]


def link_request(root: Path, session_id: str, request_id: str) -> None:
    record = sessions_store.read_session_record(root, session_id)
    activity = dict(record.get("activity") or {})
    activity["request-ids"] = sorted({*activity.get("request-ids", []), request_id})
    sessions_store.write_session_record(root, {**record, "activity": activity})


def make_project(tmp_path) -> Path:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    return root


def blocked_reason(report, session_id):
    return next(item["reason"] for item in report["blocked"] if item.get("session-id") == session_id)
