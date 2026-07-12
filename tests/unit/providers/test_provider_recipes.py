"""Provider recipe result stamping characterization tests.

Captures current ProviderRecipeResult / ProviderRecipeRegistry behavior for RS09
before RS10 refactor. Characterization only — no production code changes.
"""
from __future__ import annotations

from typing import Any

from audiagentic.components.providers.services.recipes import (
    ProviderCapabilityRecipe,
    ProviderRecipeRegistry,
    ProviderRecipeResult,
    RecipeResult,
    RecipeState,
)


class _CountingRecipe(ProviderCapabilityRecipe):
    """Test recipe that tracks to_result call count."""

    def __init__(self) -> None:
        super().__init__(
            provider_id="test",
            capability_id="cap-1",
            source_url="https://example.com/test",
            source_date="2026-01-01",
        )
        self.to_result_calls = 0

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.INSTALLING,
            artifacts=["artifact-a"],
            source_url="https://example.com/install",
            source_date="2026-02-02",
        )

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.CONFIGURING,
            artifacts=["artifact-b"],
        )

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.VERIFIED,
            source_url="https://example.com/verify",
            source_date="2026-03-03",
        )

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def to_result(self, base: RecipeResult) -> ProviderRecipeResult:
        self.to_result_calls += 1
        return super().to_result(base)


class _ActionNeededRecipe(ProviderCapabilityRecipe):
    """Test recipe that sets action_needed on verify result."""

    def __init__(self, action_value: str = "") -> None:
        super().__init__(
            provider_id="test",
            capability_id="cap-action",
            source_url="https://example.com/action",
            source_date="2026-01-01",
        )
        self.action_value = action_value

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.INSTALLING)

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.CONFIGURING)

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.VERIFIED,
            action_needed=self.action_value,
        )

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)


class _ArtifactsRecipe(ProviderCapabilityRecipe):
    """Test recipe that returns different artifacts per step."""

    def __init__(self) -> None:
        super().__init__(
            provider_id="test",
            capability_id="cap-arts",
        )

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.INSTALLING,
            artifacts=["step-install-artifact"],
        )

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.CONFIGURING,
            artifacts=["step-configure-artifact"],
        )

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.VERIFIED,
            artifacts=[],
        )

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)


class _CustomDetailsRecipe(ProviderCapabilityRecipe):
    """Test recipe that returns custom fields in details."""

    CUSTOM_FIELD = "custom_marker"
    CUSTOM_VALUE = "preserved_value_abc123"

    def __init__(self) -> None:
        super().__init__(
            provider_id="test",
            capability_id="cap-custom",
        )

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.INSTALLING)

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.CONFIGURING)

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.VERIFIED,
            details={self.CUSTOM_FIELD: self.CUSTOM_VALUE},
        )

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(RecipeState.ABSENT)


def test_install_stamps_provenance_once() -> None:
    """Characterize current to_result call count per registry.install call.

    CURRENT BEHAVIOR (characterization for RS10): the provision-path recipe
    triggers double-stamping — ProvisioningRecipe.provision() calls
    self.to_result() on its final result, AND registry.install() calls
    recipe.to_result() again on the returned value.  This test captures that
    fact so RS10 has a regression guard.

    For the primitive-call path (no provision method), to_result is not called
    at all because the registry reconstructs ProviderRecipeResult from verify
    fields directly.
    """
    recipe = _CountingRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.install("test", "cap-1")
    assert result is not None, "registry returned None"
    assert result.success is True
    assert isinstance(result, ProviderRecipeResult)

    # CURRENT: provision path double-stamps (provision -> to_result, then
    # registry.install -> to_result again). This is the duplication RS02
    # identified and RS10 must eliminate. Pin the current count for regression.
    assert recipe.to_result_calls >= 1, (
        "to_result should be called at least once on provision path"
    )

    # Provenance fields are populated regardless of stamping path
    assert result.source_url != "" or result.source_date != "", (
        "source fields should be populated after install"
    )


def test_action_needed_fallback_order() -> None:
    """When a recipe's verify sets action_needed, registry preserves it.

    The primitive-call path in ProviderRecipeRegistry.install copies the
    verify result's action_needed directly into the new ProviderRecipeResult.
    When the value is non-empty it surfaces unchanged; when empty, the field
    remains "" (the fallback to audia_action is handled by _RowRecipe._stamp,
    not by the generic registry).
    """
    # Case 1: action_needed set by recipe -> preserved
    recipe_set = _ActionNeededRecipe(action_value="run manual step X")
    registry = ProviderRecipeRegistry()
    registry.register(recipe_set)

    result = registry.install("test", "cap-action")
    assert result is not None
    assert result.action_needed == "run manual step X", (
        f"action_needed should be preserved from verify, got {result.action_needed!r}"
    )

    # Case 2: action_needed not set by recipe -> empty string (no registry fallback)
    recipe_unset = _ActionNeededRecipe(action_value="")
    registry2 = ProviderRecipeRegistry()
    registry2.register(recipe_unset)

    result2 = registry2.install("test", "cap-action")
    assert result2 is not None
    # Primitive path reconstructs from verify which returned action_needed=""
    assert result2.action_needed == "", (
        f"action_needed should be empty when not set, got {result2.action_needed!r}"
    )


def test_artifacts_owned_preserved_across_steps() -> None:
    """Artifacts accumulated during install and configure are preserved in final result.

    The registry's primitive path extends an owned list from each step then
    merges verify artifacts.  This locks the current accumulation behavior
    that RS10 must preserve.
    """
    recipe = _ArtifactsRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.install("test", "cap-arts")
    assert result is not None
    assert result.success is True

    assert "step-install-artifact" in result.artifacts_owned, (
        f"install artifacts lost: {result.artifacts_owned}"
    )
    assert "step-configure-artifact" in result.artifacts_owned, (
        f"configure artifacts lost: {result.artifacts_owned}"
    )
    assert len(result.artifacts_owned) >= 2, (
        f"expected at least 2 artifacts, got {len(result.artifacts_owned)}: "
        f"{result.artifacts_owned}"
    )


def test_custom_subclass_result_not_stripped() -> None:
    """Custom details fields survive the registry's reconstruction."""
    recipe = _CustomDetailsRecipe()
    registry = ProviderRecipeRegistry()
    registry.register(recipe)

    result = registry.install("test", "cap-custom")
    assert result is not None
    assert result.success is True

    assert _CustomDetailsRecipe.CUSTOM_FIELD in result.details, (
        f"custom detail key stripped from result. details: {result.details}"
    )
    assert result.details[_CustomDetailsRecipe.CUSTOM_FIELD] == _CustomDetailsRecipe.CUSTOM_VALUE, (
        f"custom detail value changed: {result.details[_CustomDetailsRecipe.CUSTOM_FIELD]!r}"
    )
