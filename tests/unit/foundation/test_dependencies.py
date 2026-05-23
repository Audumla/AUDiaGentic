from __future__ import annotations

from dataclasses import dataclass

from audiagentic.foundation.dependencies import (
    DependencySpec,
    install_dependencies,
    uninstall_dependencies,
)
from audiagentic.foundation.invoke.base import InvocationRecipe
from audiagentic.foundation.invoke.context import InvocationContext
from audiagentic.foundation.invoke.recipes import PlatformRecipe, ShellRecipe
from audiagentic.foundation.invoke.result import InvocationResult
from audiagentic.foundation.output import ComponentOutputEvent


@dataclass
class StateRecipe(InvocationRecipe):
    state: dict[str, bool]
    dependency_id: str
    ran: list[str]
    verifies: bool = True

    def plan(self, context: InvocationContext) -> InvocationResult:
        return InvocationResult(status="planned")

    def run(self, context: InvocationContext) -> InvocationResult:
        self.ran.append(self.dependency_id)
        context.progress(f"recipe {self.dependency_id}")
        if self.verifies:
            self.state[self.dependency_id] = True
        return InvocationResult(status="ok")


def test_dependency_service_orders_requirements_and_passes_progress() -> None:
    state = {"gh": False, "gh-mcp": False}
    ran: list[str] = []
    catalog = {
        "gh": DependencySpec(
            id="gh",
            check=lambda: state["gh"],
            install=StateRecipe(state, "gh", ran),
        ),
        "gh-mcp": DependencySpec(
            id="gh-mcp",
            check=lambda: state["gh-mcp"],
            install=StateRecipe(state, "gh-mcp", ran),
            requires=("gh",),
        ),
    }
    events: list[ComponentOutputEvent] = []

    result = install_dependencies(catalog, ["gh-mcp"], on_progress=events.append)

    assert ran == ["gh", "gh-mcp"]
    assert [entry["name"] for entry in result["results"]] == ["gh", "gh-mcp"]
    assert all(entry["ok"] for entry in result["results"])
    assert any(event.message == "recipe gh-mcp" for event in events)
    assert any(event.total == 2.0 for event in events)


def test_dependency_service_reports_verification_failure_reason() -> None:
    state = {"tool": False}
    catalog = {
        "tool": DependencySpec(
            id="tool",
            check=lambda: state["tool"],
            install=StateRecipe(state, "tool", [], verifies=False),
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
            uninstall=StateRecipe(state, "gh", ran),
        ),
        "gh-mcp": DependencySpec(
            id="gh-mcp",
            check=lambda: state["gh-mcp"],
            uninstall=StateRecipe(state, "gh-mcp", ran),
            requires=("gh",),
        ),
    }

    uninstall_dependencies(catalog, ["gh-mcp"])

    assert ran == ["gh-mcp"]


def test_platform_recipe_uses_variant_before_platform_fallback() -> None:
    recipe = PlatformRecipe(
        variants={"winget": ShellRecipe(("winget", "install", "pkg"))},
        platform_fallback={"win": ShellRecipe(("fallback", "pkg"))},
        detect_fn=lambda: "winget",
    )

    result = recipe.plan(InvocationContext(dry_run=True))

    assert result.command == ["winget", "install", "pkg"]


def test_platform_recipe_uses_platform_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        "audiagentic.foundation.invoke.recipes.platform.platform_key",
        lambda: "linux",
    )
    recipe = PlatformRecipe(
        variants={},
        platform_fallback={"linux": ShellRecipe(("sh", "install.sh"))},
        detect_fn=lambda: "apt",
    )

    result = recipe.plan(InvocationContext(dry_run=True))

    assert result.command == ["sh", "install.sh"]
