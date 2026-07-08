"""Provider-owned capability recipe contract.

Defines the types and registry for provider-scoped recipes that manage
capability integrations (MCP servers, hooks, plugins, language servers, etc.)
per provider + capability + backend.

Layering (SL11/SL12/SL13):
- foundation/toolchains = lifecycle contract (ProvisioningRecipe, RecipeResult)
  + reusable install patterns (recipe_patterns: DeclaredStepRecipe,
  NoAutomationRecipe). Domain-neutral; returns plain RecipeResult.
- this module (providers/services) = the registry + the provenance overlay
  (ProviderCapabilityRecipe.to_result stamps source/action_needed once at the
  dispatch boundary).
- a capability (e.g. memory/hindsight) = data + thin wiring that binds a
  pattern to its payloads.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from audiagentic.foundation.toolchains.recipe_contract import (
    ProvisioningRecipe,
    RecipeResult,
    RecipeState,
)


class ProviderRecipeKind(str, Enum):
    """Strategy kinds for provider capability integrations."""

    COMMAND_INSTALLER = "command_installer"
    """Installer command (npm, uv, brew, pip, etc.)."""

    MCP_CONFIG = "mcp_config"
    """MCP server entry in harness config."""

    HOOKS = "hooks"
    """Hook scripts or event wiring."""

    PLUGIN_CONFIG = "plugin_config"
    """Plugin registration/config."""

    RULES = "rules"
    """Rules/instructions files."""

    WRAPPER_CLI = "wrapper_cli"
    """Wrapper CLI or proxy binary."""

    CONTEXT_PROVIDER = "context_provider"
    """Context provider integration."""

    NATIVE_PASSTHROUGH = "native_passthrough"
    """Native harness capability, no extra config."""

    HYBRID = "hybrid"
    """Combination of strategies."""

    GUIDANCE_ONLY = "guidance_only"
    """Documentation/action-needed only, no automation."""


@dataclass(frozen=True)
class ProviderRecipeResult:
    """Provider-specific recipe operation result.

    Extends the generic RecipeResult with provider-scoped fields for source
    tracking and user-facing action guidance.
    """

    success: bool
    state: RecipeState
    artifacts_owned: list[str] = field(default_factory=list)
    status: str = ""
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    source_url: str = ""
    """URL to official integration docs for the capability recipe."""
    source_date: str = ""
    """Date the source was checked (ISO format)."""
    action_needed: str = ""
    """User-facing guidance when automation is not possible."""

    @classmethod
    def ok(
        cls,
        state: RecipeState,
        *,
        artifacts: list[str] | None = None,
        status: str = "",
        details: dict[str, Any] | None = None,
        source_url: str = "",
        source_date: str = "",
        action_needed: str = "",
    ) -> ProviderRecipeResult:
        return cls(
            success=True,
            state=state,
            artifacts_owned=list(artifacts or []),
            status=status,
            details=dict(details or {}),
            source_url=source_url,
            source_date=source_date,
            action_needed=action_needed,
        )

    @classmethod
    def fail(
        cls,
        error: str,
        *,
        state: RecipeState = RecipeState.ERROR,
        details: dict[str, Any] | None = None,
        source_url: str = "",
        action_needed: str = "",
    ) -> ProviderRecipeResult:
        return cls(
            success=False,
            state=state,
            error=error,
            details=dict(details or {}),
            source_url=source_url,
            action_needed=action_needed,
        )


class ProviderCapabilityRecipe(ProvisioningRecipe):
    """Abstract provider-scoped recipe for capability integrations.

    Extends the foundation ProvisioningRecipe with provider-specific metadata
    and lifecycle support. Concrete recipes are keyed by (provider_id,
    capability_id, backend_id) in a ProviderRecipeRegistry.

    Supports lifecycle operations: probe, install, configure, verify,
    uninstall, prune, and dry_run.
    """

    provider_id: str
    capability_id: str
    backend_id: str | None
    recipe_kind: ProviderRecipeKind
    display_name: str = ""
    source_url: str = ""
    source_date: str = ""

    def __init__(
        self,
        provider_id: str,
        capability_id: str,
        *,
        backend_id: str | None = None,
        recipe_kind: ProviderRecipeKind = ProviderRecipeKind.HYBRID,
        display_name: str = "",
        source_url: str = "",
        source_date: str = "",
    ) -> None:
        super().__init__()
        self.provider_id = provider_id
        self.capability_id = capability_id
        self.backend_id = backend_id
        self.recipe_kind = recipe_kind
        self.display_name = display_name
        self.source_url = source_url
        self.source_date = source_date

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        """Preview what install would do without mutating anything.

        Default: run probe and return the planned state. Override for
        command-based recipes that can enumerate planned shell commands.
        """
        probed = self.probe(context)
        if probed.success and probed.state is RecipeState.VERIFIED:
            return ProviderRecipeResult.ok(
                RecipeState.VERIFIED,
                status="already provisioned (dry-run)",
                source_url=self.source_url,
                source_date=self.source_date,
            )
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="would install (dry-run)",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def to_result(self, base: RecipeResult) -> ProviderRecipeResult:
        """Convert a generic RecipeResult to ProviderRecipeResult.

        Called by the base orchestration on every provision/teardown return,
        including results that are already ProviderRecipeResult — provider
        fields (action_needed, source_*) carried by the input are preserved.
        """
        return ProviderRecipeResult(
            success=base.success,
            state=base.state,
            artifacts_owned=list(base.artifacts_owned),
            status=base.status,
            error=base.error,
            details=dict(base.details),
            # source_url/source_date are provider-only fields absent from a
            # plain RecipeResult, so they stay defensive; action_needed is a
            # universal RecipeResult field (SL11) and is read directly.
            source_url=getattr(base, "source_url", "") or self.source_url,
            source_date=getattr(base, "source_date", "") or self.source_date,
            action_needed=base.action_needed,
        )


def _stamped(recipe: Any, result: Any) -> Any:
    """Route a primitive result through the recipe's provenance stamp.

    Recipes overlay provenance in ``to_result``; this is the single boundary
    where primitive results (probe/prune/dry_run) get stamped, so the
    primitives themselves can return plain RecipeResult (SL11).
    """
    to_result = getattr(recipe, "to_result", None)
    return to_result(result) if callable(to_result) else result


class ProviderRecipeRegistry:
    """Registry for provider capability recipes.

    Recipes are keyed by (provider_id, capability_id, backend_id).
    Supports listing, status querying, and lifecycle dispatch.

    Accepts any object with the recipe interface (provider_id, capability_id,
    backend_id, recipe_kind, probe, install, configure, verify, uninstall, prune).
    """

    def __init__(self) -> None:
        self._recipes: dict[tuple[str, str, str | None], Any] = {}

    def register(self, recipe: Any) -> None:
        """Register a recipe in the registry."""
        key = (recipe.provider_id, recipe.capability_id, recipe.backend_id)
        self._recipes[key] = recipe

    def get(
        self,
        provider_id: str,
        capability_id: str,
        backend_id: str | None = None,
    ) -> Any | None:
        """Look up a recipe by key."""
        return self._recipes.get((provider_id, capability_id, backend_id))

    def list_for_provider(
        self,
        provider_id: str,
        capability_id: str | None = None,
    ) -> list[Any]:
        """List all recipes for a provider, optionally filtered by capability."""
        results = []
        for (pid, cid, bid), recipe in self._recipes.items():
            if pid != provider_id:
                continue
            if capability_id is not None and cid != capability_id:
                continue
            results.append(recipe)
        return results

    def list_for_capability(
        self,
        capability_id: str,
    ) -> list[Any]:
        """List all recipes for a capability across all providers."""
        return [
            recipe
            for (pid, cid, bid), recipe in self._recipes.items()
            if cid == capability_id
        ]

    def status(
        self,
        provider_id: str,
        capability_id: str,
        backend_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProviderRecipeResult | None:
        """Get status for a recipe without mutating anything.

        The primitive result is routed through the recipe's ``to_result`` hook
        so provenance stamping happens once at this boundary rather than inside
        every ``probe`` implementation (SL11).
        """
        recipe = self.get(provider_id, capability_id, backend_id)
        if recipe is None:
            return None
        ctx = context or {}
        return _stamped(recipe, recipe.probe(ctx))

    def install(
        self,
        provider_id: str,
        capability_id: str,
        backend_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProviderRecipeResult | None:
        """Install a recipe (probe -> install -> configure -> verify)."""
        recipe = self.get(provider_id, capability_id, backend_id)
        if recipe is None:
            return None
        ctx = context or {}
        if hasattr(recipe, "provision"):
            result = recipe.provision(ctx)
            return recipe.to_result(result) if hasattr(recipe, "to_result") else result

        probed = recipe.probe(ctx)
        if probed.success and probed.state is RecipeState.VERIFIED:
            return probed
        owned: list[str] = []
        for op in (recipe.install, recipe.configure):
            result = op(ctx)
            owned.extend(result.artifacts_owned)
            if not result.success:
                return ProviderRecipeResult(
                    success=result.success,
                    state=result.state,
                    artifacts_owned=owned,
                    status=result.status,
                    error=result.error,
                    details=dict(result.details),
                    source_url=result.source_url,
                    source_date=result.source_date,
                    action_needed=result.action_needed,
                )
        verified = recipe.verify(ctx)
        return ProviderRecipeResult(
            success=verified.success,
            state=verified.state,
            artifacts_owned=[*owned, *verified.artifacts_owned],
            status=verified.status,
            error=verified.error,
            details=dict(verified.details),
            source_url=verified.source_url,
            source_date=verified.source_date,
            action_needed=verified.action_needed,
        )

    def uninstall(
        self,
        provider_id: str,
        capability_id: str,
        backend_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProviderRecipeResult | None:
        """Uninstall a recipe (prune -> uninstall -> cleanup -> verify absent)."""
        recipe = self.get(provider_id, capability_id, backend_id)
        if recipe is None:
            return None
        ctx = context or {}
        if hasattr(recipe, "teardown"):
            result = recipe.teardown(ctx)
            return recipe.to_result(result) if hasattr(recipe, "to_result") else result

        for op in (recipe.prune, recipe.uninstall):
            result = op(ctx)
            if not result.success:
                return result
        probed = recipe.probe(ctx)
        if probed.success and probed.state is RecipeState.ABSENT:
            return ProviderRecipeResult.ok(RecipeState.ABSENT, status="removed")
        return ProviderRecipeResult.fail("integration still present after teardown")

    def dry_run(
        self,
        provider_id: str,
        capability_id: str,
        backend_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProviderRecipeResult | None:
        """Preview install without mutating anything."""
        recipe = self.get(provider_id, capability_id, backend_id)
        if recipe is None:
            return None
        ctx = context or {}
        if hasattr(recipe, "dry_run"):
            return _stamped(recipe, recipe.dry_run(ctx))
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="would install (dry-run)",
            source_url=getattr(recipe, "source_url", ""),
            source_date=getattr(recipe, "source_date", ""),
        )

    def repair(
        self,
        provider_id: str,
        capability_id: str,
        backend_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> ProviderRecipeResult | None:
        """Repair: prune stale artifacts, then reinstall."""
        recipe = self.get(provider_id, capability_id, backend_id)
        if recipe is None:
            return None
        ctx = context or {}
        pruned = recipe.prune(ctx)
        if not pruned.success:
            return _stamped(recipe, pruned)
        return self.install(provider_id, capability_id, backend_id, ctx)


__all__ = [
    "ProviderCapabilityRecipe",
    "ProviderRecipeKind",
    "ProviderRecipeRegistry",
    "ProviderRecipeResult",
]
