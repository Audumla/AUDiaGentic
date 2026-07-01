"""Provider recipe lifecycle tests.

Verifies that ProviderRecipeRegistry.install() runs the full provision flow
(probe -> install -> configure -> verify) and uninstall() runs full teardown
(prune -> uninstall -> cleanup -> verify absent).
"""
from __future__ import annotations

from typing import Any

from audiagentic.components.providers.services.recipes import (
    ProviderRecipeKind,
    ProviderRecipeRegistry,
    ProviderRecipeResult,
    RecipeState,
)


class _TestRecipe:
    """Test recipe that tracks method call order."""

    def __init__(self, provider_id: str = "test", capability_id: str = "test-cap") -> None:
        self.provider_id = provider_id
        self.capability_id = capability_id
        self.backend_id = None
        self.recipe_kind = ProviderRecipeKind.HYBRID
        self.display_name = "Test"
        self.source_url = ""
        self.source_date = ""
        self.calls: list[str] = []

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("probe")
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("install")
        return ProviderRecipeResult.ok(RecipeState.INSTALLING)

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("configure")
        return ProviderRecipeResult.ok(RecipeState.CONFIGURING)

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("verify")
        return ProviderRecipeResult.ok(RecipeState.VERIFIED)

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("uninstall")
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("prune")
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def provision(self, context: dict[str, Any]) -> ProviderRecipeResult:
        """Run probe -> install -> configure -> verify."""
        probed = self.probe(context)
        if probed.success and probed.state is RecipeState.VERIFIED:
            return ProviderRecipeResult.ok(RecipeState.VERIFIED, status="already provisioned")

        owned: list[str] = []
        for op in (self.install, self.configure):
            result = op(context)
            owned.extend(result.artifacts_owned)
            if not result.success:
                return ProviderRecipeResult(
                    success=result.success, state=result.state,
                    artifacts_owned=owned, status=result.status,
                    error=result.error, details=dict(result.details),
                    source_url=result.source_url, source_date=result.source_date,
                    action_needed=result.action_needed,
                )

        verified = self.verify(context)
        return ProviderRecipeResult(
            success=verified.success, state=verified.state,
            artifacts_owned=[*owned, *verified.artifacts_owned],
            status=verified.status, error=verified.error,
            details=dict(verified.details), source_url=verified.source_url,
            source_date=verified.source_date, action_needed=verified.action_needed,
        )

    def teardown(self, context: dict[str, Any]) -> ProviderRecipeResult:
        """Run prune -> uninstall -> verify absent."""
        pruned = self.prune(context)
        if not pruned.success:
            return pruned

        removed = self.uninstall(context)
        if not removed.success:
            return removed

        probed = self.probe(context)
        if probed.success and probed.state is RecipeState.ABSENT:
            return ProviderRecipeResult.ok(RecipeState.ABSENT, status="removed")
        return ProviderRecipeResult.fail("still present after teardown")

    def to_result(self, base) -> ProviderRecipeResult:
        return base


class _FailingInstallRecipe(_TestRecipe):
    """Recipe whose install step fails."""

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("install")
        return ProviderRecipeResult.fail("install failed")


class _FailingConfigureRecipe(_TestRecipe):
    """Recipe whose configure step fails."""

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("configure")
        return ProviderRecipeResult.fail("configure failed")


class _PrimitiveRecipe:
    """Recipe with only primitive lifecycle methods, no provision/teardown helpers."""

    def __init__(self, provider_id: str = "test", capability_id: str = "test-cap") -> None:
        self.provider_id = provider_id
        self.capability_id = capability_id
        self.backend_id = None
        self.recipe_kind = ProviderRecipeKind.HYBRID
        self.calls: list[str] = []

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("probe")
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("install")
        return ProviderRecipeResult.ok(RecipeState.INSTALLING)

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("configure")
        return ProviderRecipeResult.ok(RecipeState.CONFIGURING)

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("verify")
        return ProviderRecipeResult.ok(RecipeState.VERIFIED)

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("prune")
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        self.calls.append("uninstall")
        return ProviderRecipeResult.ok(RecipeState.ABSENT)


def test_install_runs_full_provision_flow() -> None:
    """install() must call probe -> install -> configure -> verify."""
    recipe = _TestRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.install("test", "test-cap")
    assert result is not None
    assert result.success is True
    assert result.state is RecipeState.VERIFIED

    # Verify full flow was executed
    assert recipe.calls == ["probe", "install", "configure", "verify"], (
        f"Expected full provision flow, got {recipe.calls}"
    )


def test_install_composes_primitives_when_no_provision_method() -> None:
    recipe = _PrimitiveRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.install("test", "test-cap")
    assert result is not None
    assert result.success is True
    assert recipe.calls == ["probe", "install", "configure", "verify"]


def test_install_stops_on_install_failure() -> None:
    """install() must stop and not call configure/verify when install fails."""
    recipe = _FailingInstallRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.install("test", "test-cap")
    assert result is not None
    assert result.success is False

    # configure and verify must NOT be called
    assert "configure" not in recipe.calls, "configure should not run after install failure"
    assert "verify" not in recipe.calls, "verify should not run after install failure"


def test_install_stops_on_configure_failure() -> None:
    """install() must stop and not call verify when configure fails."""
    recipe = _FailingConfigureRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.install("test", "test-cap")
    assert result is not None
    assert result.success is False

    # verify must NOT be called
    assert "verify" not in recipe.calls, "verify should not run after configure failure"


def test_uninstall_runs_full_teardown_flow() -> None:
    """uninstall() must call prune -> uninstall -> verify absent."""
    recipe = _TestRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.uninstall("test", "test-cap")
    assert result is not None
    assert result.success is True
    assert result.state is RecipeState.ABSENT

    # Verify teardown flow was executed
    assert "prune" in recipe.calls, "prune should be called during teardown"
    assert "uninstall" in recipe.calls, "uninstall should be called during teardown"
    assert recipe.calls.index("prune") < recipe.calls.index("uninstall"), (
        "prune must come before uninstall"
    )


def test_uninstall_composes_primitives_when_no_teardown_method() -> None:
    recipe = _PrimitiveRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.uninstall("test", "test-cap")
    assert result is not None
    assert result.success is True
    assert recipe.calls == ["prune", "uninstall", "probe"]


def test_install_idempotent_when_already_verified() -> None:
    """install() skips when probe reports VERIFIED."""
    class VerifiedRecipe(_TestRecipe):
        def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
            self.calls.append("probe")
            return ProviderRecipeResult.ok(RecipeState.VERIFIED)

    recipe = VerifiedRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.install("test", "test-cap")
    assert result is not None
    assert result.success is True
    assert result.state is RecipeState.VERIFIED

    # Only probe should be called
    assert recipe.calls == ["probe"], (
        f"Expected idempotent skip after VERIFIED probe, got {recipe.calls}"
    )


def test_dry_run_does_not_mutate() -> None:
    """dry_run() should not call install or configure."""
    recipe = _TestRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.dry_run("test", "test-cap")
    assert result is not None
    assert "install" not in recipe.calls
    assert "configure" not in recipe.calls


def test_repair_prunes_then_installs() -> None:
    """repair() must prune stale artifacts then reinstall."""
    recipe = _TestRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.repair("test", "test-cap")
    assert result is not None

    # prune should be called first, then provision flow
    assert "prune" in recipe.calls, "repair must call prune"
    assert "install" in recipe.calls, "repair must reinstall after prune"
    assert recipe.calls.index("prune") < recipe.calls.index("install"), (
        "prune must come before install in repair"
    )
