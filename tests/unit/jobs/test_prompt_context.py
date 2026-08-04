"""Tests for prompt context construction (EDJ10)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.agent_jobs.prompt_context import (
    build_prompt_context_from_event,
    build_prompt_context_from_request,
    load_session_data,
    to_template_dict,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.event.envelope import EventEnvelope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_envelope(overrides: dict | None = None) -> EventEnvelope:
    base = {
        "type": "planning.item.created",
        "payload": {"item_id": "CC07", "title": "example item"},
        "metadata": {
            "source_component": "agent-planning",
            "subject": {"kind": "plan-item", "id": "CC07"},
            "correlation_id": "corr-abc123",
        },
        "source_component": "agent-planning",
    }
    if overrides:
        base.update(overrides)
    return EventEnvelope(**base)


def _make_trigger_config(overrides: dict | None = None) -> dict:
    base = {
        "trigger_id": "evt-plan-review",
        "kind": "event",
        "event_pattern": "planning.item.created",
    }
    if overrides:
        base.update(overrides)
    return base


def _make_request(overrides: dict | None = None) -> dict:
    base = {
        "prompt_id": "prm_001",
        "tag": "@plan",
        "source": {
            "surface": "cli",
            "session_id": "sess-001",
            "correlation_id": "corr-def456",
        },
        "target": {"kind": "adhoc"},
    }
    if overrides:
        base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------

class TestSharedContextKeysPresent:
    """Every built context must have stable top-level keys."""

    EXPECTED_KEYS = frozenset({
        "job", "project", "launch", "trigger", "event",
        "metadata", "session", "target", "agent",
    })

    def test_event_builder_has_all_keys(self) -> None:
        ctx = build_prompt_context_from_event(
            envelope=_make_envelope(),
            trigger_config=_make_trigger_config(),
            job_id="job_test_001",
            project_root="/fake/root",
            project_id="my-project",
            execution_profile_id="default-profile",
            provider_id="local-openai",
            model_id="gpt-4o",
        )
        d = to_template_dict(ctx)
        assert self.EXPECTED_KEYS.issubset(d.keys())

    def test_request_builder_has_all_keys(self) -> None:
        ctx = build_prompt_context_from_request(
            request=_make_request(),
            job_id="job_test_002",
            project_root="/fake/root",
            project_id="my-project",
            execution_profile_id="default-profile",
            provider_id="local-openai",
            model_id="gpt-4o",
        )
        d = to_template_dict(ctx)
        assert self.EXPECTED_KEYS.issubset(d.keys())

    def test_all_sections_are_dicts(self) -> None:
        ctx = build_prompt_context_from_event(
            envelope=_make_envelope(),
            job_id="job_t", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        for key in self.EXPECTED_KEYS:
            assert isinstance(d[key], dict), f"{key} must be a dict"


class TestTopLevelKeyStability:
    """Snapshot test: top-level keys do not drift."""

    def test_event_context_key_order(self) -> None:
        ctx = build_prompt_context_from_event(
            envelope=_make_envelope(),
            trigger_config=_make_trigger_config(),
            job_id="job_1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        expected_ordered = [
            "job", "project", "launch", "trigger", "event",
            "metadata", "session", "target", "agent",
            "correlation_id", "subject",
        ]
        assert list(d.keys()) == expected_ordered

    def test_request_context_key_order(self) -> None:
        ctx = build_prompt_context_from_request(
            request=_make_request({"source": {"surface": "cli", "correlation_id": "corr-x"}}),
            job_id="job_1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        expected_ordered = [
            "job", "project", "launch", "trigger", "event",
            "metadata", "session", "target", "agent",
            "correlation_id",
        ]
        assert list(d.keys()) == expected_ordered


class TestPlanningEventEnvelopeShape:
    """Live planning.item.created envelope produces correct mappings."""

    def test_planning_item_created_mapping(self) -> None:
        env = _make_envelope()
        ctx = build_prompt_context_from_event(
            envelope=env,
            trigger_config=_make_trigger_config(),
            job_id="job_ev_001",
            project_root="/proj",
            project_id="test-proj",
            execution_profile_id="agent-01",
            provider_id="claude",
            model_id="claude-3-opus",
        )
        d = to_template_dict(ctx)

        # Event section mirrors envelope fields.
        assert d["event"]["type"] == "planning.item.created"
        assert d["event"]["source_component"] == "agent-planning"
        assert d["event"]["payload"]["item_id"] == "CC07"

        # Subject from metadata propagates.
        assert d["metadata"]["subject"]["kind"] == "plan-item"
        assert d["metadata"]["subject"]["id"] == "CC07"

        # Correlation ID alias at top level.
        assert d["correlation_id"] == "corr-abc123"

        # Trigger section populated.
        assert d["trigger"]["id"] == "evt-plan-review"
        assert d["trigger"]["event_pattern"] == "planning.item.created"

        # Plan item alias injected for planning.item.created events.
        assert d["event"]["plan_item"]["id"] == "CC07"


class TestDirectLaunchContextInjection:
    """Direct launch path (code/API/CLI/MCP) builds context correctly."""

    def test_direct_launch_basic(self) -> None:
        req = _make_request()
        ctx = build_prompt_context_from_request(
            request=req,
            job_id="job_dir_001",
            project_root="/my/proj",
            project_id="main-project",
            execution_profile_id="profile-x",
            provider_id="openai",
            model_id="gpt-4",
        )
        d = to_template_dict(ctx)

        assert d["job"]["id"] == "job_dir_001"
        assert d["project"]["root"] == "/my/proj"
        assert d["project"]["id"] == "main-project"
        assert d["launch"]["surface"] == "cli"
        assert d["launch"]["input"]["prompt_id"] == "prm_001"
        assert d["agent"]["profile_id"] == "profile-x"
        assert d["agent"]["provider_id"] == "openai"
        assert d["agent"]["model_id"] == "gpt-4"

    def test_trigger_section_empty_for_direct_launch(self) -> None:
        req = _make_request()
        ctx = build_prompt_context_from_request(
            request=req,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        assert d["trigger"] == {}

    def test_event_section_empty_for_direct_launch(self) -> None:
        req = _make_request()
        ctx = build_prompt_context_from_request(
            request=req,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        assert d["event"] == {}


class TestMetadataCorrelationPropagation:
    """Correlation ID and subject propagate through context."""

    def test_event_correlation_id_propagates(self) -> None:
        env = _make_envelope()
        ctx = build_prompt_context_from_event(
            envelope=env,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        assert d["correlation_id"] == "corr-abc123"
        assert d["metadata"]["correlation_id"] == "corr-abc123"

    def test_request_correlation_id_propagates(self) -> None:
        req = _make_request()
        ctx = build_prompt_context_from_request(
            request=req,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        assert d["correlation_id"] == "corr-def456"
        assert d["metadata"]["correlation_id"] == "corr-def456"

    def test_subject_alias_present(self) -> None:
        env = _make_envelope()
        ctx = build_prompt_context_from_event(
            envelope=env,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        assert "subject" in d
        assert d["subject"]["kind"] == "plan-item"


class TestRedactionDenylist:
    """Sensitive fields are removed from context sections."""

    def test_tokens_redacted_in_event_payload(self) -> None:
        env = EventEnvelope(
            type="test.event",
            payload={
                "data": "safe-value",
                "token": "sk-1234567890abcdef",
                "api_key": "my-secret-key",
            },
            metadata={},
        )
        ctx = build_prompt_context_from_event(
            envelope=env,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        event_payload = d["event"]["payload"]
        assert "token" not in event_payload
        assert "api_key" not in event_payload
        assert "data" in event_payload

    def test_secrets_redacted_deeply(self) -> None:
        env = EventEnvelope(
            type="test.event",
            payload={"nested": {"secret": "hidden-password", "password": "my-pass"}},
            metadata={},
        )
        ctx = build_prompt_context_from_event(
            envelope=env,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        nested = d["event"]["payload"]["nested"] if (d := to_template_dict(ctx)) else {}
        assert "secret" not in nested
        assert "password" not in nested

    def test_prompt_body_redacted_in_request(self) -> None:
        req = _make_request({"prompt-body": "user prompt text"})
        ctx = build_prompt_context_from_request(
            request=req,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        # The prompt-body key should not appear in any section.
        assert "prompt-body" not in json.dumps(d)

    def test_output_field_redacted(self) -> None:
        env = EventEnvelope(
            type="test.event",
            payload={"output": "model response content"},
            metadata={},
        )
        ctx = build_prompt_context_from_event(
            envelope=env,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        assert "output" not in d["event"]["payload"]


class TestSizeLimits:
    """Per-section 4KB limit enforcement."""

    def test_small_section_passes(self) -> None:
        env = EventEnvelope(
            type="test.event",
            payload={"key": "value"},
            metadata={},
        )
        ctx = build_prompt_context_from_event(
            envelope=env,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        # All sections are small enough.
        for key, section in d.items():
            if isinstance(section, dict):
                serialized = json.dumps(section)
                assert len(serialized) <= 4 * 1024 + 100, f"{key} exceeds budget"

    def test_large_payload_truncates(self) -> None:
        env = EventEnvelope(
            type="test.event",
            payload={"big": "x" * (8 * 1024)},
            metadata={},
        )
        ctx = build_prompt_context_from_event(
            envelope=env,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        event_section_bytes = len(json.dumps(d["event"]))
        assert event_section_bytes <= 4 * 1024 + 50, "event section should be under 4KB"
        # The truncation marker should be present somewhere in the payload.
        payload = d["event"]["payload"]
        if isinstance(payload, str):
            assert "...truncated" in payload
        elif isinstance(payload, dict):
            big_value = payload.get("big", "")
            assert isinstance(big_value, str) and "...truncated" in big_value


class TestMissingOptionalSessionData:
    """Graceful handling of absent session data."""

    def test_no_session_data_returns_empty(self) -> None:
        ctx = build_prompt_context_from_event(
            envelope=_make_envelope(),
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        assert d["session"] == {}

    def test_explicit_session_data_included(self) -> None:
        session_input = {"user": "alice", "workspace": "/code"}
        ctx = build_prompt_context_from_event(
            envelope=_make_envelope(),
            session_data=session_input,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        assert d["session"]["user"] == "alice"
        assert d["session"]["workspace"] == "/code"

    def test_no_session_in_request_builder(self) -> None:
        ctx = build_prompt_context_from_request(
            request=_make_request(),
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        assert d["session"] == {}


class TestLoadSessionData:
    """load_session_data reads from NDJSON store correctly."""

    def test_empty_store_returns_empty(self, tmp_path: Path) -> None:
        result = load_session_data(str(tmp_path), "nonexistent")
        assert result == {}

    def test_records_loaded_from_input_files(self, tmp_path: Path) -> None:
        jobs_root = tmp_path / ".audiagentic" / "runtime" / "jobs"
        job_dir = jobs_root / "job_001"
        job_dir.mkdir(parents=True)

        records = [
            {"contract-version": "v1", "job-id": "job_001", "surface": "cli", "message": "hello"},
            {"contract-version": "v1", "job-id": "job_002", "surface": "api", "message": "world"},
        ]
        input_path = job_dir / "input.ndjson"
        input_path.write_text(
            "\n".join(json.dumps(r) for r in records),
            encoding="utf-8",
        )

        result = load_session_data(str(tmp_path), "sess-any")
        assert result["session_id"] == "sess-any"
        assert result["record_count"] == 2
        assert "job_001" in result["jobs"]
        assert "job_002" in result["jobs"]

    def test_permission_error_raises_IO_CTX_002(self, tmp_path: Path, monkeypatch) -> None:
        jobs_root = tmp_path / ".audiagentic" / "runtime" / "jobs"
        jobs_root.mkdir(parents=True)
        input_file = jobs_root / "job_001"
        input_file.mkdir()
        ndjson = input_file / "input.ndjson"
        ndjson.write_text('{"test": 1}', encoding="utf-8")

        original_read_text = Path.read_text

        def denied_read_text(path: Path, *args, **kwargs):
            if path == ndjson:
                raise PermissionError("test permission denial")
            return original_read_text(path, *args, **kwargs)

        # A deterministic boundary simulation works under Docker's root user
        # as well as normal host users; chmod cannot guarantee denial for root.
        monkeypatch.setattr(Path, "read_text", denied_read_text)
        with pytest.raises(AudiaGenticError) as exc_info:
            load_session_data(str(tmp_path), "sess-x")
        assert exc_info.value.code == "IO-CTX-002"


class TestTemplateDictDottedPathAccess:
    """to_template_dict produces structure navigable via dotted paths."""

    def test_nested_path_values(self) -> None:
        env = _make_envelope()
        ctx = build_prompt_context_from_event(
            envelope=env,
            trigger_config=_make_trigger_config(),
            job_id="job_dp_001",
            project_root="/nested/path",
            project_id="deep-proj",
            execution_profile_id="profile-a",
            provider_id="anthropic",
            model_id="claude-3",
        )
        d = to_template_dict(ctx)

        # Simulate dotted path resolution.
        assert _resolve("job.id", d) == "job_dp_001"
        assert _resolve("project.root", d) == "/nested/path"
        assert _resolve("event.type", d) == "planning.item.created"
        assert _resolve("trigger.event_pattern", d) == "planning.item.created"
        assert _resolve("agent.provider_id", d) == "anthropic"
        assert _resolve("metadata.subject.kind", d) == "plan-item"

    def test_flat_alias_access(self) -> None:
        env = _make_envelope()
        ctx = build_prompt_context_from_event(
            envelope=env,
            job_id="j1", project_root="/r", project_id="p",
            execution_profile_id="ap", provider_id="prov", model_id="m",
        )
        d = to_template_dict(ctx)
        assert _resolve("correlation_id", d) == "corr-abc123"


def _resolve(path: str, ctx: dict) -> object:
    """Simulate the dotted-path resolution from render_template."""
    current = ctx
    for seg in path.split("."):
        if isinstance(current, dict) and seg in current:
            current = current[seg]
        else:
            raise KeyError(f"{path} not found")
    return current
