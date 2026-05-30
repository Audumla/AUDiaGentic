from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audiagentic.foundation.dependencies import (
    DependencySpec,
    _PlatformStep,
    install_dependencies,
    uninstall_dependencies,
)
from audiagentic.foundation.output import ComponentOutputEvent
from audiagentic.foundation.workflow.invocation.models import StepResult
from audiagentic.foundation.workflow.invocation.steps import ShellStep


@dataclass
class _FakeStep:
    state: dict[str, bool]
    dependency_id: str
    ran: list[str]
    verifies: bool = True

    def run(self, context: dict[str, Any]) -> StepResult:
        self.ran.append(self.dependency_id)
        if self.verifies:
            self.state[self.dependency_id] = True
        return StepResult(status="ok")


def test_dependency_service_orders_requirements_and_passes_progress() -> None:
    state = {"gh": False, "gh-mcp": False}
    ran: list[str] = []
    catalog = {
        "gh": DependencySpec(
            id="gh",
            check=lambda: state["gh"],
            install=_FakeStep(state, "gh", ran),
        ),
        "gh-mcp": DependencySpec(
            id="gh-mcp",
            check=lambda: state["gh-mcp"],
            install=_FakeStep(state, "gh-mcp", ran),
            requires=("gh",),
        ),
    }
    events: list[ComponentOutputEvent] = []

    result = install_dependencies(catalog, ["gh-mcp"], on_progress=events.append)

    assert ran == ["gh", "gh-mcp"]
    assert [entry["name"] for entry in result["results"]] == ["gh", "gh-mcp"]
    assert all(entry["ok"] for entry in result["results"])
    assert any("gh-mcp" in event.message for event in events)
    assert any(event.total == 2.0 for event in events)


def test_dependency_service_reports_verification_failure_reason() -> None:
    state = {"tool": False}
    catalog = {
        "tool": DependencySpec(
            id="tool",
            check=lambda: state["tool"],
            install=_FakeStep(state, "tool", [], verifies=False),
        ),
    }

    result = install_dependencies(catalog, ["tool"])

    entry = result["results"][0]
    assert entry["ok"] is False
    assert entry["verified"] is False
    assert entry["error"] == "install command succeeded but dependency probe failed"


def test_dependency_uninstall_does_not_remove_requirements() -> None:
    state = {"gh": True, "gh-mcp": True}
    ran: list[str] = []
    catalog = {
        "gh": DependencySpec(
            id="gh",
            check=lambda: state["gh"],
            uninstall=_FakeStep(state, "gh", ran),
        ),
        "gh-mcp": DependencySpec(
            id="gh-mcp",
            check=lambda: state["gh-mcp"],
            uninstall=_FakeStep(state, "gh-mcp", ran),
            requires=("gh",),
        ),
    }

    uninstall_dependencies(catalog, ["gh-mcp"])

    assert ran == ["gh-mcp"]


def test_platform_step_uses_variant_before_fallback() -> None:
    step = _PlatformStep(
        variants={"winget": ShellStep(id="install", command=("winget", "install", "pkg"))},
        platform_fallback={"win": ShellStep(id="install", command=("fallback", "pkg"))},
        detect_fn=lambda: "winget",
    )

    result = step.run({})

    assert result.status in {"ok", "failed", "planned"}
    assert result.outputs.get("command", ("winget",))[0] == "winget"


def test_platform_step_uses_platform_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "audiagentic.foundation.dependencies.platform_key",
        lambda: "linux",
    )
    step = _PlatformStep(
        variants={},
        platform_fallback={"linux": ShellStep(id="install", command=("sh", "install.sh"))},
        detect_fn=lambda: None,
    )

    result = step.run({})

    assert result.status in {"ok", "failed"}
    assert result.outputs.get("command", ("sh",))[0] == "sh"


def test_platform_step_fails_when_no_variant_matches(monkeypatch) -> None:
    monkeypatch.setattr(
        "audiagentic.foundation.dependencies.platform_key",
        lambda: "unknown",
    )
    step = _PlatformStep(variants={}, detect_fn=lambda: None)

    result = step.run({})

    assert result.status == "failed"
    assert result.reason is not None
