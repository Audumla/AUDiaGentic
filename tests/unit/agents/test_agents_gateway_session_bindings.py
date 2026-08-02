from __future__ import annotations

import pytest

from audiagentic.components.agents import agents_gateway_session_bindings as bindings
from audiagentic.foundation.contracts.errors import AudiaGenticError

# ── existing test (AS19) ─────────────────────────────────────


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

    projected = bindings.project_session_capabilities(record)

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


# ── resume_binding negative tests ────────────────────────────────


class TestResumeBindingNegative:
    def test_empty_provider_ref_raises(self) -> None:
        with pytest.raises(AudiaGenticError, match="provider ref is empty") as exc_info:
            bindings.resume_binding(
                session_id="ses-test",
                provider_id="test-provider",
                surface_id="acp-session",
                provider_ref="",
                predecessor_binding_id="sbin_prev-123",
            )
        assert exc_info.value.code == "VAL-AGW-100"

    def test_none_provider_ref_raises(self) -> None:
        with pytest.raises(AudiaGenticError, match="provider ref is empty") as exc_info:
            bindings.resume_binding(
                session_id="ses-test",
                provider_id="test-provider",
                surface_id="acp-session",
                provider_ref=None,  # type: ignore[arg-type]
                predecessor_binding_id="sbin_prev-123",
            )
        assert exc_info.value.code == "VAL-AGW-100"

    def test_resumed_from_relation_and_owned_ownership(self) -> None:
        binding = bindings.resume_binding(
            session_id="ses-test",
            provider_id="test-provider",
            surface_id="acp-session",
            provider_ref="ref-resume-42",
            predecessor_binding_id="sbin_prev-123",
        )
        assert binding["relation"] == "resumed-from"
        assert binding["ownership"] == "owned"
        assert binding["predecessor-binding-id"] == "sbin_prev-123"


# ── replace_binding negative tests ───────────────────────────────


class TestReplaceBindingNegative:
    def test_empty_provider_ref_raises(self) -> None:
        with pytest.raises(AudiaGenticError, match="provider ref is empty") as exc_info:
            bindings.replace_binding(
                session_id="ses-test",
                provider_id="test-provider",
                surface_id="acp-session",
                provider_ref="",
                predecessor_binding_id="sbin_prev-456",
            )
        assert exc_info.value.code == "VAL-AGW-101"

    def test_none_provider_ref_raises(self) -> None:
        with pytest.raises(AudiaGenticError, match="provider ref is empty") as exc_info:
            bindings.replace_binding(
                session_id="ses-test",
                provider_id="test-provider",
                surface_id="acp-session",
                provider_ref=None,  # type: ignore[arg-type]
                predecessor_binding_id="sbin_prev-456",
            )
        assert exc_info.value.code == "VAL-AGW-101"

    def test_replaced_relation_distinct_from_resumed_from(self) -> None:
        resume = bindings.resume_binding(
            session_id="ses-test",
            provider_id="test-provider",
            surface_id="acp-session",
            provider_ref="ref-resume-42",
            predecessor_binding_id="sbin_prev-123",
        )
        replace = bindings.replace_binding(
            session_id="ses-test",
            provider_id="test-provider",
            surface_id="acp-session",
            provider_ref="ref-replace-99",
            predecessor_binding_id="sbin_prev-456",
        )
        assert resume["relation"] == "resumed-from"
        assert replace["relation"] == "replaced"
        assert resume["relation"] != replace["relation"]

    def test_replaced_relation_and_owned_ownership(self) -> None:
        binding = bindings.replace_binding(
            session_id="ses-test",
            provider_id="test-provider",
            surface_id="acp-session",
            provider_ref="ref-replace-99",
            predecessor_binding_id="sbin_prev-456",
        )
        assert binding["relation"] == "replaced"
        assert binding["ownership"] == "owned"
        assert binding["predecessor-binding-id"] == "sbin_prev-456"
