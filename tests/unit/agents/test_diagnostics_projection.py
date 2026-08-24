from __future__ import annotations

import json

from audiagentic.components.agents.status.diagnostics_projection import project_public_diagnostics


def test_public_diagnostics_is_closed_and_redacted() -> None:
    result = project_public_diagnostics(
        {
            "request-id": "req-1",
            "session-id": "ses-1",
            "state": "failed",
            "diagnostics": {
                "classification": "provider-error",
                "failure-code": "EXT-X-1",
                "command": "secret command",
                "recovery": {"disposition": "reconcile-required", "allowed-actions": ["reconcile"]},
            },
            "evidence": [
                {"kind": "activity", "source": "worker", "token": "do-not-leak", "path": "C:\\secret"}
            ],
            "latest-transition": {"event": "failed", "state": "failed", "timestamp": "now", "attributes": {"x": 1}},
            "provider-metadata": {"password": "secret"},
        }
    )

    assert set(result) == {
        "request-id", "session-id", "state", "diagnostics", "evidence",
        "latest-transition", "truncated",
    }
    assert "command" not in result["diagnostics"]
    assert "token" not in result["evidence"][0]
    assert "path" not in result["evidence"][0]
    assert "attributes" not in result["latest-transition"]


def test_public_diagnostics_has_deterministic_encoded_bound() -> None:
    payload = {
        "request-id": "req-1",
        "evidence": [{"kind": "activity", "source": "worker", "sequence": i} for i in range(100)],
    }
    result = project_public_diagnostics(payload, max_bytes=1024)
    encoded = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert len(encoded) <= 1024
    assert result["truncated"] is True
    assert len(result["evidence"]) < 100
