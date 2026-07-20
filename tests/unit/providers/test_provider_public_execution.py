from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers import providers_api
from audiagentic.components.providers.services import public_execution
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _request(base_root: Path, **overrides) -> providers_api.ProviderExecutionRequest:
    values = {
        "project_root": base_root.resolve(),
        "provider_id": "fixture",
        "model_id": "model-a",
        "model_alias": None,
        "packet_data": {"prompt-body": "runtime only"},
        "worker_id": "worker-1",
        "attempt_epoch": 2,
        "provider_isolation_tier": "full-isolation",
    }
    values.update(overrides)
    return providers_api.ProviderExecutionRequest(**values)


def test_execution_contract_round_trips_wire_mapping(tmp_path: Path) -> None:
    request = _request(tmp_path)

    restored = providers_api.ProviderExecutionRequest.from_mapping(
        request.to_mapping()
    )

    assert restored == request
    result = providers_api.ProviderExecutionResult(
        provider_id="fixture",
        model_id="model-a",
        worker_id="worker-1",
        attempt_epoch=2,
        result_data={"status": "ok", "output": "done"},
    )
    assert providers_api.ProviderExecutionResult.from_mapping(
        result.to_mapping()
    ) == result


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"project_root": Path("relative")}, "VAL-PEXE-001"),
        ({"worker_id": ""}, "VAL-PEXE-002"),
        ({"attempt_epoch": 0}, "VAL-PEXE-002"),
        ({"model_id": None, "model_alias": None}, "VAL-MODEL-002"),
        ({"provider_isolation_tier": "invented"}, "VAL-PEXE-003"),
    ],
)
def test_execution_request_rejects_incomplete_identity(
    tmp_path: Path,
    overrides: dict,
    code: str,
) -> None:
    with pytest.raises(AudiaGenticError) as captured:
        _request(tmp_path, **overrides)

    assert captured.value.code == code


def test_execute_turn_uses_provider_owned_resolution_and_attempt_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        tmp_path,
        packet_data={
            "prompt-body": "runtime only",
            "working-root": "C:/wrong",
            "provider-id": "wrong",
            "model-id": "wrong",
        },
    )
    monkeypatch.setattr(
        public_execution,
        "get_provider_runtime_config_state",
        lambda *_args: {
            "provider-id": "fixture",
            "enabled": True,
            "config": {"access-mode": "cli"},
        },
    )
    monkeypatch.setattr(
        public_execution,
        "get_provider_execution_isolation_tier",
        lambda _provider_id: "full-isolation",
    )

    from audiagentic.components.providers.services import execution, models

    monkeypatch.setattr(
        models,
        "resolve_model_selection",
        lambda **_kwargs: {"model-id": "model-a"},
    )
    observed: dict = {}

    def fake_execute_provider(**kwargs):
        observed.update(kwargs)
        return {"status": "ok", "output": "done", "model": "model-a"}

    monkeypatch.setattr(execution, "execute_provider", fake_execute_provider)

    result = providers_api.execute_provider_turn(request)

    assert result.worker_id == "worker-1"
    assert result.attempt_epoch == 2
    assert result.result_data["output"] == "done"
    assert observed["packet_ctx"]["working-root"] == str(tmp_path.resolve())
    assert observed["packet_ctx"]["provider-id"] == "fixture"
    assert observed["packet_ctx"]["model-id"] == "model-a"


def test_execute_turn_rejects_descriptor_tier_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        public_execution,
        "get_provider_runtime_config_state",
        lambda *_args: {"provider-id": "fixture", "enabled": True, "config": {}},
    )
    monkeypatch.setattr(
        public_execution,
        "get_provider_execution_isolation_tier",
        lambda _provider_id: "partial-isolation",
    )

    with pytest.raises(AudiaGenticError) as captured:
        providers_api.execute_provider_turn(_request(tmp_path))

    assert captured.value.code == "CON-PEXE-001"


def test_runtime_state_is_provider_scoped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from audiagentic.components.providers.services import provider_config

    monkeypatch.setattr(
        provider_config,
        "load_provider_config",
        lambda _root: {
            "providers": {
                "fixture": {"default-model": "model-a"},
                "unrelated": {"secret-ref": "must-not-leak"},
            }
        },
    )
    monkeypatch.setattr(
        provider_config,
        "is_provider_enabled",
        lambda _root, provider_id: provider_id == "fixture",
    )

    state = providers_api.get_provider_runtime_config_state(tmp_path, "fixture")

    assert state == {
        "provider-id": "fixture",
        "enabled": True,
        "config": {"default-model": "model-a"},
    }
    assert "unrelated" not in repr(state)


def test_prepare_acp_launch_keeps_provider_resolution_behind_public_seam(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        public_execution,
        "get_provider_runtime_config_state",
        lambda *_args: {"provider-id": "fixture", "enabled": True, "config": {}},
    )
    from audiagentic.components.providers.services import execution, models
    from audiagentic.foundation.transports import AcpLaunch

    monkeypatch.setattr(
        execution,
        "load_acp_launch_builder",
        lambda _provider_id: lambda root, *, model_id: AcpLaunch("fixture", (model_id,)),
    )
    monkeypatch.setattr(
        models,
        "resolve_model_selection",
        lambda **_kwargs: {"model-id": "model-a"},
    )

    result = providers_api.prepare_provider_acp_launch(
        tmp_path, provider_id="fixture", model_id="wanted", model_alias=None
    )

    assert result.provider_id == "fixture"
    assert result.model_id == "model-a"
    assert (result.launch.executable, result.launch.args) == ("fixture", ("model-a",))


def test_prepare_acp_launch_rejects_unsupported_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        public_execution,
        "get_provider_runtime_config_state",
        lambda *_args: {"provider-id": "fixture", "enabled": True, "config": {}},
    )
    from audiagentic.components.providers.services import execution

    monkeypatch.setattr(execution, "load_acp_launch_builder", lambda _provider_id: None)

    with pytest.raises(AudiaGenticError) as captured:
        providers_api.prepare_provider_acp_launch(
            tmp_path, provider_id="fixture", model_id="wanted", model_alias=None
        )
    assert captured.value.code == "UNS-PEXE-002"


def test_prepare_execution_env_uses_project_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The execution environment builder must read from project-level config
    so that custom providers added by model_source_add/apply_model_sources are
    included in the inline OPENCODE_CONFIG_CONTENT passed to isolated workers."""
    import json

    from audiagentic.components.providers.services import models

    # Write a global config WITHOUT the custom provider (simulates real state).
    global_config = Path.home() / ".config" / "opencode"
    global_config.mkdir(parents=True, exist_ok=True)
    (global_config / "opencode.json").write_text(
        json.dumps({"provider": {"anthropic": {}}}), encoding="utf-8"
    )

    # Write project-level config WITH the custom provider.
    project_config = tmp_path / ".opencode" / "opencode.json"
    project_config.parent.mkdir(parents=True, exist_ok=True)
    (project_config).write_text(
        json.dumps({"provider": {"anthropic": {}, "audiagentic": {}}}), encoding="utf-8"
    )

    monkeypatch.setattr(
        public_execution,
        "get_provider_runtime_config_state",
        lambda *_args: {"provider-id": "opencode", "enabled": True, "config": {}},
    )

    monkeypatch.setattr(
        models,
        "resolve_model_selection",
        lambda **_kwargs: {"model-id": "model-a"},
    )

    result = providers_api.prepare_provider_execution_environment(_request(tmp_path, provider_id="opencode"))

    doc = json.loads(result["OPENCODE_CONFIG_CONTENT"])
    assert "audiagentic" in doc.get("enabled_providers", [])

    # Restore global config.
    (global_config / "opencode.json").write_text(
        json.dumps({"provider": {"anthropic": {}, "audiagentic": {}}}), encoding="utf-8"
    )
