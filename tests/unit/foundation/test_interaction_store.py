from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.foundation import interaction
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event import get_bus, reset_bus
from audiagentic.foundation.interaction import ResponseStatus
from audiagentic.foundation.paths.names import project_marker_path


def _events() -> list[tuple[str, dict]]:
    seen: list[tuple[str, dict]] = []
    get_bus().subscribe("interaction.*", lambda event, payload, metadata: seen.append((event, payload)))
    return seen


def teardown_function() -> None:
    interaction.clear_backend()
    reset_bus()


def test_interaction_request_respond_roundtrip(tmp_path: Path) -> None:
    seen = _events()
    request_id = interaction.request_interaction(
        "job-approval",
        "Approve job?",
        choices=("approved", "rejected"),
        source_kind="job-service",
        source_id="job-1",
        project_root=tmp_path,
    )

    assert interaction.get_response(request_id, project_root=tmp_path) is None

    interaction.respond(
        request_id,
        "approved",
        details={"reason": "ok"},
        project_root=tmp_path,
    )
    response = interaction.get_response(request_id, project_root=tmp_path)

    assert response is not None
    assert response.status is ResponseStatus.ANSWERED
    assert response.choice == "approved"
    assert response.details == {"reason": "ok"}
    assert [event for event, _ in seen] == ["interaction.requested", "interaction.answered"]


def test_interaction_request_expires_lazily(tmp_path: Path) -> None:
    request_id = interaction.request_interaction(
        "ask",
        "Continue?",
        project_root=tmp_path,
        ttl_seconds=1,
    )

    response = interaction.get_response(
        request_id,
        project_root=tmp_path,
        now_ts="2999-01-01T00:00:00Z",
    )

    assert response is not None
    assert response.status is ResponseStatus.TIMED_OUT
    payload = json.loads(
        (project_marker_path(tmp_path) / "runtime" / "interactions" / f"{request_id}.json")
        .read_text(encoding="utf-8")
    )
    assert payload["state"] == "expired"


def test_interaction_schema_rejects_malformed_record(tmp_path: Path) -> None:
    root = project_marker_path(tmp_path) / "runtime" / "interactions"
    root.mkdir(parents=True)
    (root / "bad.json").write_text('{"request_id": "bad"}', encoding="utf-8")

    with pytest.raises(AudiaGenticError) as exc_info:
        interaction.get_response("bad", project_root=tmp_path)

    assert exc_info.value.code == "VAL-INTERACT-001"


def test_push_status_publishes_event(tmp_path: Path) -> None:
    del tmp_path
    seen = _events()

    interaction.push_status("providers", "Reconciled", details={"count": 1})

    assert seen == [
        (
            "interaction.status",
            {
                "component": "providers",
                "level": "info",
                "message": "Reconciled",
                "details": {"count": 1},
            },
        )
    ]


def test_ask_persist_fallback_creates_pending_record(tmp_path: Path) -> None:
    response = interaction.ask("Continue?", persist=True, project_root=tmp_path)

    assert response.status is ResponseStatus.TIMED_OUT
    request_id = response.details["request_id"]
    payload = json.loads(
        (project_marker_path(tmp_path) / "runtime" / "interactions" / f"{request_id}.json")
        .read_text(encoding="utf-8")
    )
    assert payload["state"] == "pending"
