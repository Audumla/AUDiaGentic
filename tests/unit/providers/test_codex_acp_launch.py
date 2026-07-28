"""AS13 — codex ACP session launch capability tests."""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.services.execution.execution import load_acp_launch_builder


def test_codex_exposes_acp_launch_builder():
    builder = load_acp_launch_builder("codex")
    assert builder is not None


def test_codex_launch_prefers_local_binary(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.codex.acp as codex_acp

    monkeypatch.setattr(codex_acp.shutil, "which", lambda name: r"C:\tools\codex-acp.cmd" if name == "codex-acp" else None)
    launch = codex_acp.build_acp_launch(tmp_path)
    assert launch.executable == r"C:\tools\codex-acp.cmd"
    assert launch.args == ()


def test_codex_launch_falls_back_to_npx(monkeypatch, tmp_path):
    import audiagentic.components.providers.adapters.codex.acp as codex_acp

    def fake_which(name):
        return r"C:\nodejs\npx.cmd" if name == "npx" else None

    monkeypatch.setattr(codex_acp.shutil, "which", fake_which)
    monkeypatch.setattr("audiagentic.components.providers.adapters.cli.shutil.which", fake_which)
    launch = codex_acp.build_acp_launch(Path(tmp_path))
    assert launch.executable.endswith("npx.cmd")
    assert launch.args == ("-y", "@agentclientprotocol/codex-acp")


def test_opencode_still_exposes_builder():
    assert load_acp_launch_builder("opencode") is not None


def test_provider_without_acp_module_returns_none():
    assert load_acp_launch_builder("no-such-provider") is None
