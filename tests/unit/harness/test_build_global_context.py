"""HA03 slice 1: build_global_context unified across pi and opencode."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.runtime.harness.run_common import build_global_context


def _patch_common(monkeypatch: pytest.MonkeyPatch, *, harness_available: bool = True) -> None:
    monkeypatch.setattr(
        "audiagentic.runtime.harness.resolution.harness_cli_available",
        lambda harness_type: ("/usr/bin/" + harness_type) if harness_available else None,
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.config.load_harness_config",
        lambda project_root=None: {"rig": {"model": "qwen3.5-0.8b", "provider": "audiagentic", "port": 42001}},
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.config.require_harness_rig_port",
        lambda harness_cfg: 42001,
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.config.require_harness_provider",
        lambda harness_cfg: "audiagentic",
    )
    monkeypatch.setattr(
        "audiagentic.runtime.rig.embedded.config.load_rig_model",
        lambda: ("qwen3.5-0.8b", "qwen3.5-0.8b"),
    )
    monkeypatch.setattr(
        "audiagentic.runtime.rig.models.load_model_profile",
        lambda requested, model: ("qwen3.5-0.8b", {"agent": {}}),
    )
    monkeypatch.setattr(
        "audiagentic.runtime.harness.rig.launch_rig_if_needed",
        lambda *a, **kw: __import__(
            "audiagentic.runtime.harness.rig", fromlist=["RigConnection"]
        ).RigConnection("http://127.0.0.1:42001/v1", "qwen3.5-0.8b", True),
    )
    monkeypatch.setattr(
        "audiagentic.runtime.rig.models.query_server_model",
        lambda endpoint: "qwen3.5-0.8b",
    )
    monkeypatch.setattr(
        "audiagentic.runtime.rig.models.query_server_version",
        lambda bin_dir: "b1234",
    )


def test_missing_harness_cli_fails_before_any_rig_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch, harness_available=False)
    rig_calls: list[object] = []
    monkeypatch.setattr(
        "audiagentic.runtime.harness.rig.launch_rig_if_needed",
        lambda *a, **kw: rig_calls.append(1),
    )

    with pytest.raises(AudiaGenticError) as excinfo:
        build_global_context(
            "pi", project_root=tmp_path, agent_runtime=tmp_path / "runtime", enable_mcp=True
        )

    assert excinfo.value.code == "RES-HRNRUN-001"
    assert rig_calls == []


def test_pi_context_is_harness_blind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """HA03: no pi-specific fields on the generic context -- that's provider-owned now."""
    _patch_common(monkeypatch)
    agent_runtime = tmp_path / "runtime"

    ctx = build_global_context(
        "pi", project_root=tmp_path, agent_runtime=agent_runtime, enable_mcp=True
    )

    assert not hasattr(ctx, "agent_home")
    assert not hasattr(ctx, "agent_dir")
    assert not hasattr(ctx, "agent_bin")
    assert ctx.agent_runtime == agent_runtime
    assert ctx.provider == "audiagentic"
    assert ctx.model == "qwen3.5-0.8b"
    assert ctx.server_version == "b1234"


def test_opencode_context_matches_pi_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HA03: pi and opencode now build the identical generic context shape."""
    _patch_common(monkeypatch)
    agent_runtime = tmp_path / "runtime"

    ctx = build_global_context(
        "opencode", project_root=tmp_path, agent_runtime=agent_runtime, enable_mcp=True
    )

    assert not hasattr(ctx, "agent_home")
    assert not hasattr(ctx, "agent_dir")
    assert not hasattr(ctx, "agent_bin")
    assert ctx.agent_runtime == agent_runtime
    assert ctx.provider == "audiagentic"


def test_missing_model_raises_canonical_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        "audiagentic.runtime.harness.config.load_harness_config",
        lambda project_root=None: {"rig": {}},
    )
    monkeypatch.delenv("AUDIAGENTIC_AG_MODEL", raising=False)

    with pytest.raises(AudiaGenticError) as excinfo:
        build_global_context(
            "opencode", project_root=tmp_path, agent_runtime=tmp_path / "runtime", enable_mcp=True
        )

    assert excinfo.value.code == "CFG-HCFG-009"


def test_env_model_overrides_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_common(monkeypatch)
    seen_requested: list[str] = []
    monkeypatch.setattr(
        "audiagentic.runtime.rig.models.load_model_profile",
        lambda requested, model: (seen_requested.append(model) or "profile", {"agent": {}}),
    )
    monkeypatch.setenv("AUDIAGENTIC_AG_MODEL", "env-model")

    build_global_context(
        "pi", project_root=tmp_path, agent_runtime=tmp_path / "runtime", enable_mcp=True
    )

    assert seen_requested == ["env-model"]
