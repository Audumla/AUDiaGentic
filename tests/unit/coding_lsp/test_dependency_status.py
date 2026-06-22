from __future__ import annotations

from pathlib import Path

from audiagentic.components.coding_lsp import coding_lsp_bootstrap, language_registry
from audiagentic.foundation.components.dependencies import build_dependency_install_commands


def test_install_commands_for_pyright_from_registry() -> None:
    commands = build_dependency_install_commands(
        language_registry.dependency_cfgs(), ["pyright"], workflow_id="coding-lsp"
    )
    assert commands["pyright"] == [["uv", "tool", "install", "pyright"]]


def test_install_commands_for_clangd_uses_platform_variant() -> None:
    commands = build_dependency_install_commands(
        language_registry.dependency_cfgs(), ["clangd"], workflow_id="coding-lsp"
    )
    assert commands["clangd"] == [["winget", "install", "--id", "LLVM.LLVM", "-e", "--accept-source-agreements", "--accept-package-agreements"]]


def test_status_payload_uses_workflow_derived_install_commands(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(coding_lsp_bootstrap, "_active_dependency_ids", lambda project_root: ["pyright"])
    monkeypatch.setattr(coding_lsp_bootstrap, "detect_missing", lambda probes, names: ["pyright"])
    monkeypatch.setattr(
        "audiagentic.components.coding_lsp.lsp_config_api.active_dependency_cfgs",
        lambda project_root: language_registry.dependency_cfgs(["python"]),
    )

    payload = coding_lsp_bootstrap.status_payload(tmp_path)

    assert payload["missing-dependencies"] == ["pyright"]
    assert payload["dependency-install-offer"] == "Install Pyright (Python LSP): uv tool install pyright"


def test_on_installed_creates_dirs_without_writing_lsp_json(tmp_path: Path) -> None:
    coding_lsp_bootstrap._on_installed(tmp_path)

    assert (tmp_path / ".coding-lsp").is_dir()
    assert (tmp_path / ".coding-lsp" / "logs").is_dir()
    assert not (tmp_path / ".coding-lsp" / "lsp.json").exists()
