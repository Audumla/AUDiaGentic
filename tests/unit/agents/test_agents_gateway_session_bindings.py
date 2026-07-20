from __future__ import annotations

from audiagentic.components.agents.agents_gateway_session_bindings import (
    project_session_capabilities,
)


def test_project_session_capabilities_drops_unsafe_nested_fields() -> None:
    record = {
        "capability-snapshot": {
            "surface-id": "opencode-acp",
            "declared-controls": {
                "cancel-turn": "cooperative",
                "raw-payload": {"secret": "native frame"},
                "provider-session-ref": "native-session-secret",
                "nested": {
                    "output": "model output",
                    "safe": "metadata-only",
                },
            },
            "unsupported-extra": "not projected",
            "evidence-tier": "documentation",
        }
    }

    projected = project_session_capabilities(record)

    assert projected == {
        "surface-id": "opencode-acp",
        "declared-controls": {
            "cancel-turn": "cooperative",
            "nested": {"safe": "metadata-only"},
        },
        "evidence-tier": "documentation",
    }
    assert "native-session-secret" not in repr(projected)
    assert "native frame" not in repr(projected)
    assert "model output" not in repr(projected)
