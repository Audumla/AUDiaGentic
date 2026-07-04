from __future__ import annotations

import subprocess
from pathlib import Path

from audiagentic.components.providers.adapters.pi import hooks as pi_desc
from audiagentic.components.providers.descriptors.base import (
    McpConfigSpec,
    ProviderDescriptor,
)
from audiagentic.components.providers.services import lsp_projection
from audiagentic.foundation.features import registry as feature_registry
from audiagentic.foundation.features.base import BindingDescriptor


def _mcp_spec() -> McpConfigSpec:
    return McpConfigSpec(
        config_path=".mcp.json",
        reader=lambda p: {},
        writer=lambda p, e: None,
        remover=lambda p, n: False,
        refresh_mode="restart-required",
    )


def setup_function() -> None:
    feature_registry.clear()


def teardown_function() -> None:
    feature_registry.clear()


def test_pi_descriptor_declares_lsp_hook() -> None:
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    pi = all_descriptors()["pi"]
    assert pi.on_lsp_enabled is pi_desc._pi_ensure_lens


def test_ensure_lens_skips_when_harness_absent(tmp_path: Path, monkeypatch) -> None:
    missing = tmp_path / "cli" / "node_modules" / ".bin" / "pi"
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.runner.context.resolve_agent_bin",
        lambda runtime: missing,
    )
    monkeypatch.setattr("audiagentic.foundation.home.global_harness_runtime", lambda: tmp_path)

    def _boom(*a, **k):
        raise AssertionError("subprocess must not run when pi bin is absent")

    monkeypatch.setattr(pi_desc.subprocess, "run", _boom)

    result = pi_desc._pi_ensure_lens(tmp_path)
    assert result["ok"] is False
    assert "not installed" in result["skipped"]


def test_ensure_lens_starts_background_install_when_harness_present(tmp_path: Path, monkeypatch) -> None:
    # Enabling runs subprocess.run directly (not threaded) and returns immediately.
    pi_bin = tmp_path / "pi"
    pi_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.runner.context.resolve_agent_bin",
        lambda runtime: pi_bin,
    )
    monkeypatch.setattr("audiagentic.foundation.home.global_harness_runtime", lambda: tmp_path)

    captured: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "installed pi-lens", "")

    monkeypatch.setattr(pi_desc.subprocess, "run", _fake_run)

    result = pi_desc._pi_ensure_lens(tmp_path)

    assert result["ok"] is True
    assert captured["cmd"] == [str(pi_bin), "install", "npm:pi-lens"]


def test_install_pi_lens_runs_install_command(tmp_path: Path, monkeypatch) -> None:
    pi_bin = tmp_path / "pi"
    pi_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "installed pi-lens", "")

    monkeypatch.setattr(pi_desc.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        "audiagentic.runtime.harness.pi.runner.context.resolve_agent_bin",
        lambda runtime: pi_bin,
    )
    monkeypatch.setattr("audiagentic.foundation.home.global_harness_runtime", lambda: tmp_path)

    pi_desc._pi_ensure_lens(tmp_path)

    assert captured["cmd"] == [str(pi_bin), "install", "npm:pi-lens"]


def test_generic_mcp_route_excludes_self_lsp_provider(tmp_path: Path, monkeypatch) -> None:
    # A provider that self-provides LSP (on_lsp_enabled set) must NOT receive ag-lsp.
    feature_registry.register(
        BindingDescriptor(
            parent="coding-lsp",
            implementation="ag-lsp",
            feature_kind="language",
            feature="python",
            projection_writer_key="coding-lsp.lsp-json",
        )
    )
    self_lsp = ProviderDescriptor(
        provider_id="selflsp",
        display_name="Self LSP",
        mcp_config=_mcp_spec(),
        on_lsp_enabled=lambda root: {"ok": True},
        receive_lsp_mcp=False,
    )
    plain = ProviderDescriptor(
        provider_id="plain",
        display_name="Plain",
        mcp_config=_mcp_spec(),
    )
    monkeypatch.setattr(
        lsp_projection, "all_descriptors", lambda: {"selflsp": self_lsp, "plain": plain}
    )
    monkeypatch.setattr(lsp_projection, "enabled_provider_ids", lambda root: {"selflsp", "plain"})

    seen: dict[str, dict] = {}

    def _capture(*, provider_id, project_root, desired_entries, managed_ids):
        seen[provider_id] = desired_entries
        return {"ok": True}

    monkeypatch.setattr(lsp_projection, "sync_managed_provider_mcp_subset", _capture)

    lsp_projection.sync_generic_lsp_mcp_to_provider_configs(
        tmp_path,
        {"coding-lsp/ag-lsp": ("ag-lsp", object())},
        {"coding-lsp/ag-lsp", "coding-lsp/blackwell-agent-lsp"},
    )
    assert "selflsp" not in seen              # excluded — receive_lsp_mcp=False
    assert "plain" in seen and seen["plain"]  # plain provider still gets ag-lsp


def test_provision_fans_out_to_hooks(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    with_hook = ProviderDescriptor(
        provider_id="hooked",
        display_name="Hooked",
        on_lsp_enabled=lambda root: calls.append("hooked") or {"ok": True},
    )
    without = ProviderDescriptor(provider_id="nohook", display_name="No hook")
    monkeypatch.setattr(
        lsp_projection, "all_descriptors", lambda: {"hooked": with_hook, "nohook": without}
    )
    monkeypatch.setattr(lsp_projection, "enabled_provider_ids", lambda root: {"hooked", "nohook"})

    result = lsp_projection.provision_provider_lsp_support(tmp_path)
    assert result["provisioned"] == ["hooked"]
    assert "nohook" in result["skipped"]
    assert calls == ["hooked"]
