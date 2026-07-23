from __future__ import annotations

import subprocess
from pathlib import Path

from audiagentic.components.providers.adapters.pi import hooks as pi_desc
from audiagentic.components.providers.descriptors.automation_capabilities import (
    ProviderAutomationCapability,
)
from audiagentic.components.providers.descriptors.base import ProviderDescriptor
from audiagentic.foundation.toolchains.managed_config import ManagedConfigSpec


def _managed_mcp_capability() -> ProviderAutomationCapability:
    """The declaration a provider needs to participate in managed-mcp."""
    return ProviderAutomationCapability(
        family_id="managed-mcp",
        supported_modes=("apply", "prune", "status"),
        payload_contract="provider-managed-mcp-payload/v1",
        result_contract="provider-managed-mcp-result/v1",
        ownership_scope_required=True,
    )


def _mcp_spec() -> ManagedConfigSpec:
    return ManagedConfigSpec(
        config_path=".mcp.json",
        reader=lambda p: {},
        writer=lambda p, e: None,
        remover=lambda p, n: False,
        refresh_mode="restart-required",
    )


def test_pi_descriptor_declares_lsp_hook() -> None:
    from audiagentic.components.providers.descriptors.registry import all_descriptors

    pi = all_descriptors()["pi"]
    assert pi.on_lsp_enabled is pi_desc._pi_ensure_lens


def test_ensure_lens_skips_when_harness_absent(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.pi.system.resolve_system_pi_executable",
        lambda: None,
    )

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
        "audiagentic.components.providers.adapters.pi.system.resolve_system_pi_executable",
        lambda: str(pi_bin),
    )

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
        "audiagentic.components.providers.adapters.pi.system.resolve_system_pi_executable",
        lambda: str(pi_bin),
    )

    pi_desc._pi_ensure_lens(tmp_path)

    assert captured["cmd"] == [str(pi_bin), "install", "npm:pi-lens"]


def test_managed_mcp_all_skips_no_capability(tmp_path: Path, monkeypatch) -> None:
    # Providers without managed-mcp capability return supported=False;
    # providers with mcp_config but no managed-mcp declaration are skipped.
    self_lsp = ProviderDescriptor(
        provider_id="selflsp",
        display_name="Self LSP",
        mcp_config=_mcp_spec(),
        on_lsp_enabled=lambda root: {"ok": True},
        receive_lsp_mcp=False,
    )
    with_cap = ProviderDescriptor(
        provider_id="withcap",
        display_name="With Capability",
        mcp_config=_mcp_spec(),
        automation_capabilities=(_managed_mcp_capability(),),
    )
    providers = {"selflsp": self_lsp, "withcap": with_cap}

    from audiagentic.components.providers.contracts.managed_mcp import (
        ManagedMcpEntry,
        ManagedMcpRequest,
    )
    from audiagentic.components.providers.providers_api import manage_mcp_entries_all

    monkeypatch.setattr(
        "audiagentic.components.providers.descriptors.registry.all_descriptors",
        lambda: providers,
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.services.managed_mcp_family.get_descriptor",
        lambda pid: providers.get(pid),
    )
    # Patch the mcp.py _descriptor which is called by sync_managed_provider_mcp_scope
    monkeypatch.setattr(
        "audiagentic.components.providers.services.mcp._descriptor",
        lambda pid: providers.get(pid),
    )
    # Mock the registry to avoid file I/O
    mock_reg = type("MockReg", (), {
        "load": lambda self: {},
        "save": lambda self, d: None,
    })()
    monkeypatch.setattr(
        "audiagentic.components.providers.services.managed_mcp_registry.mcp_ownership_registry",
        lambda root: mock_reg,
    )

    entry = ManagedMcpEntry(managed_id="coding-lsp/ag-lsp", name="ag-lsp", command="ag-lsp")
    request = ManagedMcpRequest(ownership_scope="coding-lsp/ag-lsp", entries=(entry,))

    results = manage_mcp_entries_all(
        tmp_path,
        mode="apply",
        request=request,
    )
    # Both providers have mcp_config so both appear; selflsp lacks managed-mcp cap
    assert len(results) == 2


def test_provision_fans_out_to_hooks(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    from audiagentic.components.providers.descriptors.automation_capabilities import (
        ProviderAutomationCapability,
    )

    with_hook = ProviderDescriptor(
        provider_id="hooked",
        display_name="Hooked",
        on_lsp_enabled=lambda root: calls.append("hooked") or {"ok": True},
        automation_capabilities=(ProviderAutomationCapability(
            family_id="self-provided-lsp",
            supported_modes=("apply", "status"),
            payload_contract="provider-self-provided-lsp-payload/v1",
            result_contract="provider-self-provided-lsp-result/v1",
            ownership_scope_required=False,
        ),),
    )
    without = ProviderDescriptor(provider_id="nohook", display_name="No hook")

    from audiagentic.components.coding_lsp.language_servers_sync import (
        provision_provider_lsp_support,
    )

    monkeypatch.setattr(
        "audiagentic.components.providers.descriptors.registry.all_descriptors",
        lambda: {"hooked": with_hook, "nohook": without},
    )

    def _get_descriptor(pid: str):
        return {"hooked": with_hook, "nohook": without}.get(pid)

    monkeypatch.setattr(
        "audiagentic.components.providers.services.self_provided_lsp_handler.get_descriptor",
        _get_descriptor,
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.services.feature_resolution.enabled_provider_ids",
        lambda root: {"hooked", "nohook"},
    )

    result = provision_provider_lsp_support(tmp_path)
    assert result["provisioned"] == ["hooked"]
    assert "nohook" in result["skipped"]
    assert calls == ["hooked"]


# ---------------------------------------------------------------------------
# self-provided-lsp status is a query: it must never provision (RV497)
# ---------------------------------------------------------------------------

def _self_lsp_handler(descriptor, tmp_path: Path, monkeypatch):
    from audiagentic.components.providers.services.self_provided_lsp_handler import (
        _make_self_provided_lsp_handler,
    )

    monkeypatch.setattr(
        "audiagentic.components.providers.services.self_provided_lsp_handler.get_descriptor",
        lambda pid: descriptor,
    )
    return _make_self_provided_lsp_handler(descriptor.provider_id, tmp_path)


def test_self_provided_lsp_status_does_not_run_the_install_hook(tmp_path, monkeypatch):
    installed: list[str] = []
    probed: list[str] = []

    descriptor = ProviderDescriptor(
        provider_id="hooked",
        display_name="Hooked",
        on_lsp_enabled=lambda root: installed.append("ran") or {"ok": True},
        lsp_support_probe=lambda root: probed.append("probed") or {"ok": True},
    )
    handler = _self_lsp_handler(descriptor, tmp_path, monkeypatch)

    result = handler("status", None, None)

    assert installed == []  # the mutating hook must not fire for a query
    assert probed == ["probed"]
    assert result.ok is True
    assert result.state == "provisioned"


def test_self_provided_lsp_status_reports_needs_action_when_absent(tmp_path, monkeypatch):
    descriptor = ProviderDescriptor(
        provider_id="hooked",
        display_name="Hooked",
        on_lsp_enabled=lambda root: {"ok": True},
        lsp_support_probe=lambda root: {"ok": False, "action_needed": "not installed"},
    )
    handler = _self_lsp_handler(descriptor, tmp_path, monkeypatch)

    result = handler("status", None, None)

    assert result.state == "needs-action"
    assert result.action_needed == "not installed"


def test_self_provided_lsp_status_is_evidence_only_without_a_probe(tmp_path, monkeypatch):
    installed: list[str] = []
    descriptor = ProviderDescriptor(
        provider_id="hooked",
        display_name="Hooked",
        on_lsp_enabled=lambda root: installed.append("ran") or {"ok": True},
    )
    handler = _self_lsp_handler(descriptor, tmp_path, monkeypatch)

    result = handler("status", None, None)

    assert installed == []  # still must not provision
    assert result.state == "unknown"
    assert "lsp_support_probe" in (result.action_needed or "")


def test_self_provided_lsp_apply_runs_the_install_hook(tmp_path, monkeypatch):
    installed: list[str] = []
    descriptor = ProviderDescriptor(
        provider_id="hooked",
        display_name="Hooked",
        on_lsp_enabled=lambda root: installed.append("ran") or {"ok": True},
        lsp_support_probe=lambda root: {"ok": False},
    )
    handler = _self_lsp_handler(descriptor, tmp_path, monkeypatch)

    result = handler("apply", None, None)

    assert installed == ["ran"]
    assert result.state == "provisioned"


def test_self_provided_lsp_surfaces_redacted_hook_failure_detail(tmp_path, monkeypatch):
    def _boom(root):
        raise RuntimeError("token=sk-secret-value install failed")

    descriptor = ProviderDescriptor(
        provider_id="hooked",
        display_name="Hooked",
        on_lsp_enabled=_boom,
    )
    handler = _self_lsp_handler(descriptor, tmp_path, monkeypatch)

    result = handler("apply", None, None)

    assert result.ok is False
    assert result.error_code == "CON-PSLS-002"
    assert "sk-secret-value" not in (result.action_needed or "")


def test_pi_lens_probe_does_not_shell_out(tmp_path, monkeypatch):
    pi_bin = tmp_path / "pi"
    pi_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.pi.system.resolve_system_pi_executable",
        lambda: str(pi_bin),
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.pi.system.resolve_system_pi_package",
        lambda name: (tmp_path / name) if (tmp_path / name).is_dir() else None,
    )

    def _fail(*a, **k):
        raise AssertionError("probe must not run a subprocess")

    monkeypatch.setattr(pi_desc.subprocess, "run", _fail)

    assert pi_desc._pi_lens_present(tmp_path)["ok"] is False

    package = tmp_path / "pi-lens"
    package.mkdir(parents=True)
    assert pi_desc._pi_lens_present(tmp_path)["ok"] is True
