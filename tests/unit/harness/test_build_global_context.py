"""HA03 slice 1: build_global_context unified across pi and opencode; the model server is an existing endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.harness.run_common import build_global_context


def _patch_common(monkeypatch: pytest.MonkeyPatch, *, harness_available: bool = True, served_model: str | None = "qwen3.5-0.8b") -> list[str]:
    """Patch the harness lookups; returns the list of endpoints the server was asked about."""
    asked: list[str] = []
    monkeypatch.setattr(
        "audiagentic.runtime.harness.resolution.harness_cli_available",
        lambda harness_type: ("/usr/bin/" + harness_type) if harness_available else None,
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.config.load_harness_config",
        lambda project_root=None: {"rig": {"model": "qwen3.5-0.8b", "provider": "audiagentic", "port": 42001}},
    )
    monkeypatch.setattr("audiagentic.runtime.harness.config.require_harness_rig_port", lambda harness_cfg: 42001)
    monkeypatch.setattr("audiagentic.runtime.harness.config.require_harness_provider", lambda harness_cfg: "audiagentic")
    monkeypatch.setattr("audiagentic.foundation.config.local_runtime.local_rig_host", lambda: "127.0.0.1")
    monkeypatch.delenv("AUDIAGENTIC_AG_BASE_URL", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_AG_MODEL", raising=False)

    def query(endpoint: str, timeout: float = 10.0) -> str | None:
        asked.append(endpoint)
        return served_model

    monkeypatch.setattr("audiagentic.runtime.harness.endpoint.query_server_model", query)
    return asked


def test_missing_harness_cli_fails_before_the_server_is_contacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _patch_common(monkeypatch, harness_available=False)

    with pytest.raises(AudiaGenticError) as excinfo:
        build_global_context("pi", project_root=tmp_path, agent_runtime=tmp_path / "runtime", enable_mcp=True)

    assert excinfo.value.code == "RES-HRNRUN-001"
    assert asked == []


def test_pi_context_is_harness_blind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """HA03: no pi-specific fields on the generic context -- that's provider-owned now."""
    _patch_common(monkeypatch)
    agent_runtime = tmp_path / "runtime"

    ctx = build_global_context("pi", project_root=tmp_path, agent_runtime=agent_runtime, enable_mcp=True)

    assert not hasattr(ctx, "agent_home")
    assert not hasattr(ctx, "agent_dir")
    assert not hasattr(ctx, "agent_bin")
    assert ctx.agent_runtime == agent_runtime
    assert ctx.provider == "audiagentic"
    assert ctx.model == "qwen3.5-0.8b"
    assert ctx.endpoint == "http://127.0.0.1:42001/v1"


def test_opencode_context_matches_pi_shape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """HA03: pi and opencode build the identical generic context shape."""
    _patch_common(monkeypatch)

    pi = build_global_context("pi", project_root=tmp_path, agent_runtime=tmp_path / "runtime", enable_mcp=True)
    opencode = build_global_context("opencode", project_root=tmp_path, agent_runtime=tmp_path / "runtime", enable_mcp=True)

    assert opencode.__dict__.keys() == pi.__dict__.keys()
    assert (opencode.provider, opencode.model, opencode.endpoint) == (pi.provider, pi.model, pi.endpoint)


def test_the_environment_endpoint_wins_over_the_configured_host_and_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _patch_common(monkeypatch)
    monkeypatch.setenv("AUDIAGENTIC_AG_BASE_URL", "http://models.internal:9000/v1")

    ctx = build_global_context("pi", project_root=tmp_path, agent_runtime=tmp_path / "runtime", enable_mcp=True)

    assert ctx.endpoint == "http://models.internal:9000/v1"
    assert asked == ["http://models.internal:9000/v1"]


def test_the_requested_model_is_used_when_the_server_names_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch, served_model=None)

    ctx = build_global_context("pi", project_root=tmp_path, agent_runtime=tmp_path / "runtime", enable_mcp=True)

    assert ctx.model == "qwen3.5-0.8b"


def test_the_model_the_server_reports_replaces_the_requested_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch, served_model="served-model-id")

    ctx = build_global_context("pi", project_root=tmp_path, agent_runtime=tmp_path / "runtime", enable_mcp=True)

    assert ctx.model == "served-model-id"


def test_missing_model_raises_canonical_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        "audiagentic.runtime.harness.config.load_harness_config", lambda project_root=None: {"rig": {}},
    )

    with pytest.raises(AudiaGenticError) as excinfo:
        build_global_context("opencode", project_root=tmp_path, agent_runtime=tmp_path / "runtime", enable_mcp=True)

    assert excinfo.value.code == "CFG-HCFG-009"


def test_env_model_overrides_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch, served_model=None)
    monkeypatch.setenv("AUDIAGENTIC_AG_MODEL", "env-model")

    ctx = build_global_context("pi", project_root=tmp_path, agent_runtime=tmp_path / "runtime", enable_mcp=True)

    assert ctx.model == "env-model"
