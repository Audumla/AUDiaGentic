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
