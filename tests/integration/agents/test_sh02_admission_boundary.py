"""SH02 integration tests: admission boundary validates through SubmissionEnvelope,
persists redacted ExecutionManifest, and proves no prompt/secret reaches records or events.

These tests exercise the actual submit_execution_request admission path (not the
isolated contract unit tests) to verify that the envelope validation, manifest
resolution, and record redaction work end-to-end.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.agents.agents_paths import gateway_request_path
from audiagentic.components.agents.contracts.execution_context import (
    compute_prompt_digest,
)
from audiagentic.components.agents.gateway import api as gateway
from audiagentic.components.agents.configuration.management import (
    create_execution_profile,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.features.base import ImplementationState
from audiagentic.foundation.features.state import set_implementation_state


def _make_profile(project_root: Path, profile_id: str, provider_id: str, *, default: bool = True, **params) -> None:
    create_execution_profile(project_root, {
        "profile_id": profile_id,
        "provider_id": provider_id,
        "model_id": "gpt-4o",
        "instances": ["gpt-4o"],
        "is_default": default,
        "params": params,
    })
    set_implementation_state(project_root, "providers", provider_id, ImplementationState(enabled=True))


def _worker_result(execution_request: dict, output: str) -> SimpleNamespace:
    return SimpleNamespace(
        result_data={
            "provider-id": execution_request["provider-id"],
            "status": "ok",
            "model": "gpt-4o",
            "output": output,
        }
    )


class TestRecordRedaction:
    """SH02 exit gate: persisted records must contain no raw prompt body."""

    def test_persisted_record_contains_no_raw_prompt(self, tmp_path: Path) -> None:
        _make_profile(tmp_path, "default", "local-openai")

        secret_prompt = "the launch code is sk-AAAABBBBCCCCDDDDEEEE"
        submitted = gateway.submit_execution_request(tmp_path, prompt_body=secret_prompt)
        request_id = submitted["request-id"]

        # Read the persisted record directly from disk
        record_path = gateway_request_path(tmp_path, request_id)
        assert record_path.exists()

        persisted = json.loads(record_path.read_text())

        # The raw prompt must NOT be in the persisted record
        assert persisted["prompt-body"] is None
        assert secret_prompt not in json.dumps(persisted)
        assert "sk-AAAA" not in json.dumps(persisted)

        # But the digest MUST be present
        assert persisted["prompt-digest"] == compute_prompt_digest(secret_prompt)

    def test_persisted_record_carries_manifest_fields(self, tmp_path: Path) -> None:
        _make_profile(tmp_path, "default", "local-openai")

        submitted = gateway.submit_execution_request(tmp_path, prompt_body="implement the thing")
        request_id = submitted["request-id"]

        persisted = json.loads(gateway_request_path(tmp_path, request_id).read_text())

        assert persisted["manifest-id"] is not None
        assert persisted["context-fingerprint"] is not None
        assert len(persisted["context-fingerprint"]) == 64  # SHA-256 hex
        assert persisted["prompt-digest"] is not None
        assert persisted["idempotency-key"] is not None
        assert len(persisted["idempotency-key"]) == 64  # SHA-256 hex

    def test_metadata_prompt_and_idempotency_aliases_do_not_reach_records(self, tmp_path: Path) -> None:
        _make_profile(tmp_path, "default", "local-openai")
        prompt_canary = "METADATA_SECRET_PROMPT"
        idempotency_canary = "RAW_KEY_ALIAS"
        submitted = gateway.submit_execution_request(
            tmp_path,
            prompt_body="safe user prompt",
            metadata={
                "idempotency_key": idempotency_canary,
                "prompt_body": prompt_canary,
                "nested": [{"idempotencyKey": idempotency_canary, "safe": "kept"}],
                "correlation_id": "corr-123",
                "subject": {"kind": "test"},
            },
        )

        persisted = json.loads(gateway_request_path(tmp_path, submitted["request-id"]).read_text())
        serialized = json.dumps(persisted)
        assert prompt_canary not in serialized
        assert idempotency_canary not in serialized
        assert persisted["metadata"]["correlation_id"] == "corr-123"
        assert persisted["metadata"]["subject"] == {"kind": "test"}
        assert persisted["metadata"]["nested"] == [{"safe": "kept"}]

    def test_dispatch_still_receives_raw_prompt(self, tmp_path: Path, monkeypatch) -> None:
        """The dispatch boundary must receive the raw prompt body for provider execution,
        even though it's not persisted."""
        _make_profile(tmp_path, "default", "local-openai")

        received_prompts = []

        def fake_execute_provider(*, execution_request, **_kwargs):
            received_prompts.append(execution_request["packet-data"].get("prompt-body"))
            return _worker_result(execution_request, "ok")

        monkeypatch.setattr(
            "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
            fake_execute_provider,
        )

        result = gateway.run_execution_request(tmp_path, prompt_body="the actual prompt")
        assert result["state"] == "completed"
        assert result["provider-id"] == "local-openai"
        assert result["model-id"] == "gpt-4o"
        assert len(result["attempts"]) == 1
        assert result["attempts"][0]["state"] == "completed"
        assert result["output"] == "ok"
        # Earlier redaction checks submit asynchronously. Their daemon worker
        # may still finish after this test's monkeypatch is installed, so this
        # integration assertion is about delivery of this request, not global
        # worker count.
        assert "the actual prompt" in received_prompts


class TestCredentialRejection:
    """SH02 exit gate: credential-like material in metadata is rejected."""

    @pytest.mark.parametrize(
        "credential_value",
        [
            "sk-AAAABBBBCCCCDDDDEEEE",
            "AKIAABCDEFGHIJKLMNOP",
            "Bearer abcdefghijklmnop.qrstuvwxyz",
            "-----BEGIN RSA PRIVATE KEY-----",
        ],
    )
    def test_credential_in_metadata_rejected_at_admission(self, tmp_path: Path, credential_value: str) -> None:
        _make_profile(tmp_path, "default", "local-openai")

        with pytest.raises(AudiaGenticError) as exc:
            gateway.submit_execution_request(
                tmp_path,
                prompt_body="implement the thing",
                metadata={"note": credential_value},
            )
        assert exc.value.code == "VAL-AGW-065"

    def test_nested_credential_in_metadata_is_rejected_at_admission(self, tmp_path: Path) -> None:
        _make_profile(tmp_path, "default", "local-openai")

        with pytest.raises(AudiaGenticError) as exc:
            gateway.submit_execution_request(
                tmp_path,
                prompt_body="implement the thing",
                metadata={"context": {"headers": ["Bearer abcdefghijklmnop.qrstuvwxyz"]}},
            )
        assert exc.value.code == "VAL-AGW-065"

    def test_credential_in_prompt_is_not_scanned(self, tmp_path: Path, monkeypatch) -> None:
        """Prompts may legitimately discuss keys; only metadata is canary-scanned."""
        _make_profile(tmp_path, "default", "local-openai")

        def fake_execute_provider(*, execution_request, **_kwargs):
            return _worker_result(execution_request, "ok")

        monkeypatch.setattr(
            "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
            fake_execute_provider,
        )

        # This must NOT raise VAL-AGW-065 — prompt content is exempt from scanning
        result = gateway.run_execution_request(
            tmp_path,
            prompt_body="rotate the key sk-AAAABBBBCCCCDDDDEEEE",
        )
        assert result["state"] == "completed"

    def test_prompt_content_does_not_leak_to_events(self, tmp_path: Path, monkeypatch) -> None:
        """Lifecycle events must not carry raw prompt body or secret material."""
        from audiagentic.foundation.event import get_bus

        bus = get_bus()

        _make_profile(tmp_path, "default", "local-openai")
        secret_prompt = "the password is AKIAABCDEFGHIJKLMNOP"
        metadata_prompt_canary = "METADATA_SECRET_PROMPT"
        metadata_idempotency_canary = "RAW_KEY_ALIAS"

        captured_events: list[dict] = []

        def capture_event(topic: str, payload: dict, metadata: dict | None) -> None:
            captured_events.append({"topic": topic, "payload": payload, "metadata": metadata or {}})

        for topic in ("agents.execution.queued", "agents.execution.started", "agents.execution.completed", "agents.execution.failed"):
            bus.subscribe(topic, capture_event)

        def fake_execute_provider(*, execution_request, **_kwargs):
            return _worker_result(execution_request, "done")

        monkeypatch.setattr(
            "audiagentic.components.agents.gateway.queue.worker.execute_isolated_provider_turn",
            fake_execute_provider,
        )

        result = gateway.run_execution_request(
            tmp_path,
            prompt_body=secret_prompt,
            metadata={
                "prompt_body": metadata_prompt_canary,
                "nested": {"idempotencyKey": metadata_idempotency_canary},
                "correlation_id": "corr-events",
            },
        )
        assert result["state"] == "completed"

        for event in captured_events:
            event_text = json.dumps(event)
            # No raw prompt body in events
            assert secret_prompt not in event_text
            assert "AKIAABCD" not in event_text
            assert metadata_prompt_canary not in event_text
            assert metadata_idempotency_canary not in event_text
            # payload must not contain prompt-body
            payload = event.get("payload", {})
            assert "prompt-body" not in payload or payload.get("prompt-body") is None
