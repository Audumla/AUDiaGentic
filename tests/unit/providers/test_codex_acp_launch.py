"""AS13 — codex ACP session launch capability tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.providers.adapters.codex.model_selection import split_model_selection
from audiagentic.components.providers.services.execution.execution import load_acp_launch_builder


def test_codex_exposes_acp_launch_builder():
    builder = load_acp_launch_builder("codex")
    assert builder is not None


def test_codex_model_selection_supports_effort_suffix():
    assert split_model_selection("gpt-5.6-luna[low]") == ("gpt-5.6-luna", "low")
    assert split_model_selection("gpt-5.6-luna") == ("gpt-5.6-luna", None)


@pytest.mark.parametrize("effort", ["medium", "high"])
def test_codex_acp_passes_profile_effort_to_bridge(monkeypatch, tmp_path, effort):
    """The ACP bridge receives the profile's effort, not the CLI-only key."""
    import audiagentic.components.providers.adapters.codex.acp as codex_acp

    monkeypatch.setattr(
        codex_acp.shutil,
        "which",
        lambda name: r"C:\tools\codex-acp.cmd" if name == "codex-acp" else None,
    )
    launch = codex_acp.build_acp_launch(
        tmp_path,
        model_id=f"gpt-5.6-luna[{effort}]",
    )
    config = json.loads(launch.environment["CODEX_CONFIG"])
    assert config == {"model": "gpt-5.6-luna", "reasoning_effort": effort}
    assert "model_reasoning_effort" not in config


def test_codex_launch_prefers_local_binary(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.codex.acp as codex_acp

    monkeypatch.setattr(codex_acp.shutil, "which", lambda name: r"C:\tools\codex-acp.cmd" if name == "codex-acp" else None)
    launch = codex_acp.build_acp_launch(tmp_path, model_id="gpt-5.6-luna[xhigh]")
    assert launch.executable == r"C:\tools\codex-acp.cmd"
    assert launch.args == ()
    assert launch.environment["CODEX_CONFIG"] == (
        '{"model":"gpt-5.6-luna","reasoning_effort":"xhigh"}'
    )


def test_codex_launch_falls_back_to_npx(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.codex.acp as codex_acp

    def fake_which(name):
        return r"C:\nodejs\npx.cmd" if name == "npx" else None

    monkeypatch.setattr(codex_acp.shutil, "which", fake_which)
    monkeypatch.setattr("audiagentic.components.providers.adapters.cli.shutil.which", fake_which)
    launch = codex_acp.build_acp_launch(Path(tmp_path))
    assert launch.executable.endswith("npx.cmd")
    assert launch.args == ("-y", "@agentclientprotocol/codex-acp@1.6.2")
    assert launch.environment == {}


def test_codex_launch_uses_shared_bridge_before_path_or_npx(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.codex.acp as codex_acp

    monkeypatch.setattr(
        codex_acp,
        "shared_codex_acp_node_launch",
        lambda: (r"C:\Program Files\nodejs\node.exe", (r"C:\Users\shared\codex-acp\index.js",)),
    )
    monkeypatch.setattr(
        codex_acp.shutil,
        "which",
        lambda name: r"C:\nodejs\npx.cmd" if name == "npx" else None,
    )
    monkeypatch.setattr(
        "audiagentic.components.providers.adapters.cli.shutil.which",
        lambda name: r"C:\nodejs\npx.cmd" if name == "npx" else None,
    )

    launch = codex_acp.build_acp_launch(tmp_path)

    assert launch.executable.endswith("node.exe")
    assert launch.args == (r"C:\Users\shared\codex-acp\index.js",)


def test_codex_acp_recipe_is_pinned_and_shared(tmp_path, monkeypatch):
    import audiagentic.components.providers.adapters.codex.acp_install as install

    monkeypatch.setenv("AUDIAGENTIC_HOME", str(tmp_path / "shared-home"))
    assert install.CODEX_ACP_PACKAGE == "@agentclientprotocol/codex-acp"
    assert install.CODEX_ACP_VERSION == "1.6.2"
    assert install.shared_codex_acp_root() == (
        tmp_path / "shared-home" / "providers" / "codex" / "acp" / "1.6.2"
    )
    recipe = install.codex_acp_recipe_path()
    assert recipe.name == "codex-acp-bridge.yaml"

    result = install.install_shared_codex_acp(dry_run=True)
    assert result.success
    assert "1 install" in result.status
    assert result.details["recipe_id"] == "codex-acp-bridge"


def test_shared_codex_acp_resolver_returns_direct_node_entrypoint(tmp_path, monkeypatch):
    import audiagentic.components.providers.adapters.codex.acp_install as install

    entrypoint = (
        tmp_path
        / "node_modules"
        / "@agentclientprotocol"
        / "codex-acp"
        / "dist"
        / "index.js"
    )
    entrypoint.parent.mkdir(parents=True)
    entrypoint.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    monkeypatch.setattr(install, "shared_codex_acp_root", lambda: tmp_path)
    monkeypatch.setattr(install.shutil, "which", lambda name: r"C:\nodejs\node.exe" if name == "node" else None)

    assert install.shared_codex_acp_entrypoint() == entrypoint
    assert install.shared_codex_acp_node_launch() == (
        r"C:\nodejs\node.exe",
        (str(entrypoint),),
    )


def test_codex_launch_merges_process_local_config(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.codex.acp as codex_acp

    def fake_which(name):
        return r"C:\nodejs\npx.cmd" if name == "npx" else None

    monkeypatch.setattr(codex_acp.shutil, "which", fake_which)
    monkeypatch.setattr("audiagentic.components.providers.adapters.cli.shutil.which", fake_which)
    launch = codex_acp.build_acp_launch(
        tmp_path,
        model_id="gpt-5.6-luna[max]",
        provider_config={"codex-config": {"approval_policy": "never"}},
    )
    assert launch.environment["CODEX_CONFIG"] == (
        '{"approval_policy":"never","model":"gpt-5.6-luna","reasoning_effort":"max"}'
    )


def test_opencode_still_exposes_builder():
    assert load_acp_launch_builder("opencode") is not None


def test_provider_without_acp_module_returns_none():
    assert load_acp_launch_builder("no-such-provider") is None
