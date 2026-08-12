"""SH22 real disposable-worker activity-rig conformance gate."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.agents.contracts.worker_protocol import WorkerActivityEnvelope, WorkerExecutionIdentity
from audiagentic.components.agents.gateway.queue.worker import execute_isolated_provider_turn
from audiagentic.components.providers.providers_api import ProviderExecutionRequest

pytestmark = pytest.mark.integration


def test_activity_rig_emits_authenticated_progress_sequence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from audiagentic.components.providers.services.config.provider_config import set_provider_enabled
    set_provider_enabled(tmp_path, "activity-rig", enabled=True)
    monkeypatch.setenv("AUDIAGENTIC_WORKER_ACTIVITY_SOURCES", "provider-progress,tool-progress,provider-progress")
    monkeypatch.setenv("AUDIAGENTIC_WORKER_ACTIVITY_INTERVAL_SECONDS", "0.1")
    identity = WorkerExecutionIdentity(
        worker_id="activity-rig-worker", attempt_epoch=1, manifest_id="mf_activity",
        context_fingerprint="a" * 64, project_root=str(tmp_path.resolve()),
        component_profile="base", provider_isolation_tier="full-isolation",
    )
    request = ProviderExecutionRequest(
        project_root=tmp_path.resolve(), provider_id="activity-rig", model_id="activity-rig",
        model_alias=None, packet_data={"prompt-body": "pause/tool/resume"},
        worker_id=identity.worker_id, attempt_epoch=identity.attempt_epoch,
        provider_isolation_tier="full-isolation",
    )
    frames: list[WorkerActivityEnvelope] = []
    result = execute_isolated_provider_turn(
        identity=identity, execution_request=request.to_mapping(), timeout_seconds=10,
        activity_callback=frames.append,
    )
    assert result.result_data["status"] == "completed"
    assert [frame.activity_source for frame in frames[:3]] == ["provider-progress", "tool-progress", "provider-progress"]
    assert all(frame.identity == identity for frame in frames)


def test_activity_rig_stall_after_first_activity_is_observable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from audiagentic.components.providers.services.config.provider_config import set_provider_enabled
    set_provider_enabled(tmp_path, "activity-rig", enabled=True)
    monkeypatch.setenv("AUDIAGENTIC_WORKER_ACTIVITY_SOURCES", "provider-progress,tool-progress")
    monkeypatch.setenv("AUDIAGENTIC_WORKER_ACTIVITY_INTERVAL_SECONDS", "0.1")
    monkeypatch.setenv("AUDIAGENTIC_WORKER_ACTIVITY_STALL_AFTER", "1")
    identity = WorkerExecutionIdentity(
        worker_id="activity-rig-stall", attempt_epoch=1, manifest_id="mf_stall",
        context_fingerprint="b" * 64, project_root=str(tmp_path.resolve()),
        component_profile="base", provider_isolation_tier="full-isolation",
    )
    request = ProviderExecutionRequest(
        project_root=tmp_path.resolve(), provider_id="activity-rig", model_id="activity-rig",
        model_alias=None, packet_data={"prompt-body": "stall"}, worker_id=identity.worker_id,
        attempt_epoch=1, provider_isolation_tier="full-isolation",
    )
    frames: list[WorkerActivityEnvelope] = []
    result = execute_isolated_provider_turn(
        identity=identity, execution_request=request.to_mapping(), timeout_seconds=10,
        activity_callback=frames.append,
    )
    assert result.result_data["status"] == "completed"
    assert len(frames) == 1
    assert frames[0].activity_source == "provider-progress"
