from __future__ import annotations

import subprocess

from audiagentic.components.coding_lsp import language_registry
from audiagentic.foundation.components.dependencies import build_dependency_workflow
from audiagentic.foundation.features.base import FeatureDescriptor, OptionSchema


def test_language_spec_uses_registered_feature_descriptor_options() -> None:
    descriptor = FeatureDescriptor(
        parent="coding-lsp",
        kind="language",
        feature_id="example",
        display_name="Example",
        options_schema={"mode": OptionSchema(option_type="enum", values=("on", "off"), default="on")},
        raw={
            "type": "feature",
            "parent": "coding-lsp",
            "kind": "language",
            "id": "example",
            "server": {
                "command": ["example-lsp"],
                "file-extensions": [".ex"],
            },
        },
    )

    spec = language_registry.language_spec_from_feature(descriptor)

    assert spec.id == "example"
    assert spec.command == ("example-lsp",)
    assert spec.options_schema is descriptor.options_schema


def test_typescript_dependency_installs_server_and_runtime() -> None:
    dep_cfgs = language_registry.dependency_cfgs(["typescript"])
    workflow = build_dependency_workflow(dep_cfgs, workflow_id="coding-lsp", action="install")
    step = next(s for s in workflow.steps if s.id == "typescript-language-server")
    inner = step.variants["run"]
    command = inner.command if hasattr(inner, "command") else ()
    assert command[:4] == ("npm", "install", "-g", "typescript-language-server")
    assert command[4:] == ("typescript",)


def test_typescript_dependency_uses_cross_platform_npm() -> None:
    dep_cfgs = language_registry.dependency_cfgs(["typescript"])
    cfg = dep_cfgs["typescript-language-server"]

    assert cfg["toolchain"] == "npm"
    assert cfg["package"] == ["typescript-language-server", "typescript"]
    assert cfg["probe"] == "all-binaries:typescript-language-server,tsserver"


def test_clangd_dependency_has_os_package_manager_variants() -> None:
    dep_cfgs = language_registry.dependency_cfgs(["cpp"])
    via = dep_cfgs["clangd"]["via"]

    assert via["winget"] == "LLVM.LLVM"
    assert via["scoop"] == "clangd"
    assert via["choco"] == "llvm"
    assert via["brew"] == "clangd"
    assert via["apt"] == "clangd"
    assert via["dnf"] == "clangd"
    assert via["pacman"] == "clangd"


def test_language_feature_options_are_loaded() -> None:
    spec = language_registry.get_language("python")
    assert spec is not None
    assert spec.options_schema["server-settings"].option_type == "object"
    assert spec.options_schema["server-settings"].default == {}


def test_probe_rust_analyzer_requires_working_binary(monkeypatch) -> None:
    monkeypatch.setattr(language_registry, "tool_available", lambda name: True)

    class _Result:
        returncode = 1

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: _Result(),
    )

    assert language_registry.probe_rust_analyzer() is False


def test_rust_dependency_uses_rustup_component() -> None:
    dep_cfgs = language_registry.dependency_cfgs(["rust"])
    workflow = build_dependency_workflow(dep_cfgs, workflow_id="coding-lsp", action="install")
    step = next(s for s in workflow.steps if s.id == "rust-analyzer")
    inner = step.variants["run"]
    command = inner.command if hasattr(inner, "command") else ()
    assert command == ("rustup", "component", "add", "rust-analyzer")


def test_markdown_language_registers_with_marksman() -> None:
    spec = language_registry.get_language("markdown")
    assert spec is not None
    assert spec.id == "markdown"
    assert spec.command == ("marksman", "server")
    assert set(spec.file_extensions) == {".md", ".markdown"}


def test_markdown_dependency_cfgs_includes_marksman() -> None:
    dep_cfgs = language_registry.dependency_cfgs(["markdown"])
    dep_ids = list(dep_cfgs.keys())
    assert "marksman" in dep_ids
    marksman_cfg = dep_cfgs["marksman"]
    assert marksman_cfg["probe"] == "binary:marksman"


def test_markdown_appears_in_all_languages() -> None:
    catalog = language_registry.all_languages()
    assert "markdown" in catalog
    assert catalog["markdown"].command == ("marksman", "server")


def test_json_language_registers_with_vscode_json_language_server() -> None:
    spec = language_registry.get_language("json")
    assert spec is not None
    assert spec.command == ("vscode-json-language-server", "--stdio")
    assert set(spec.file_extensions) == {".json", ".jsonc"}


def test_toml_language_registers_with_taplo() -> None:
    spec = language_registry.get_language("toml")
    assert spec is not None
    assert spec.command == ("taplo", "lsp", "stdio")
    assert set(spec.file_extensions) == {".toml"}


def test_make_language_registers_with_make_ls() -> None:
    spec = language_registry.get_language("make")
    assert spec is not None
    assert spec.command == ("make-ls",)
    assert set(spec.file_extensions) == {"Makefile", "makefile", "GNUmakefile"}


def test_json_dependency_installs_vscode_langservers_extracted() -> None:
    dep_cfgs = language_registry.dependency_cfgs(["json"])
    workflow = build_dependency_workflow(dep_cfgs, workflow_id="coding-lsp", action="install")
    step = next(s for s in workflow.steps if s.id == "vscode-langservers-extracted")
    inner = step.variants["run"]
    command = inner.command if hasattr(inner, "command") else ()
    assert command == ("npm", "install", "-g", "vscode-langservers-extracted")


def test_yaml_language_registers_with_yaml_language_server() -> None:
    spec = language_registry.get_language("yaml")
    assert spec is not None
    assert spec.command == ("yaml-language-server", "--stdio")
    assert set(spec.file_extensions) == {".yaml", ".yml"}


def test_yaml_dependency_installs_yaml_language_server() -> None:
    dep_cfgs = language_registry.dependency_cfgs(["yaml"])
    workflow = build_dependency_workflow(dep_cfgs, workflow_id="coding-lsp", action="install")
    step = next(s for s in workflow.steps if s.id == "yaml-language-server")
    inner = step.variants["run"]
    command = inner.command if hasattr(inner, "command") else ()
    assert command == ("npm", "install", "-g", "yaml-language-server")
