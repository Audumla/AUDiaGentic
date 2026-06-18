from __future__ import annotations

import subprocess

from audiagentic.components.optional.coding_lsp import language_registry
from audiagentic.foundation.components.dependencies import build_dependency_workflow


def test_typescript_dependency_installs_server_and_runtime() -> None:
    dep_cfgs = language_registry.dependency_cfgs(["typescript"])
    workflow = build_dependency_workflow(dep_cfgs, workflow_id="coding-lsp", action="install")
    step = next(s for s in workflow.steps if s.id == "typescript-language-server")
    inner = step.variants["run"]
    command = inner.command if hasattr(inner, "command") else ()
    assert command[:4] == ("npm", "install", "-g", "typescript-language-server")
    assert command[4:] == ("typescript",)


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
