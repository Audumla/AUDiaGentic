"""Hindsight implementation recipes with provider-facing strategy dispatch.

Registers Hindsight capability recipes per provider, using matrix data from this
implementation package. Each recipe strategy type dispatches to the appropriate
implementation. Hindsight-specific provider setup is contained here; the
providers component exposes only generic recipe interfaces.
"""
from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.matrix import (
    HINDSIGHT_RECIPE_MATRIX,
    HindsightRecipeRow,
)
from audiagentic.components.memory.hindsight.mcp_recipe import (
    HindsightMcpRecipe,
    HindsightTarget,
)
from audiagentic.components.memory.hindsight_export import (
    HindsightBackendConfig,
    build_hindsight_backend,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.components.providers.services.recipes import (
    ProviderRecipeKind,
    ProviderRecipeRegistry,
    ProviderRecipeResult,
    RecipeState,
)
from audiagentic.foundation.toolchains.probes import CommandProbe

_SHELL_METACHARS = ("|", "&&", ";", ">", "<")


def _command_parts(command: str) -> list[str]:
    """Return argv for a simple command, refusing shell compound syntax."""
    if any(token in command for token in _SHELL_METACHARS):
        raise ValueError(
            "shell compound command requires structured shell-step support"
        )
    return shlex.split(command)


class HooksInstallerRecipe:
    """Command-installer recipe: runs official hook installer CLI.

    For providers like Codex, Cline that use hook scripts installed via CLI.
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        backend: HindsightBackendConfig,
    ) -> None:
        self.provider_id = row.provider_id
        self.capability_id = "hindsight"
        self.backend_id = None
        self.recipe_kind = row.recipe_kind
        self.display_name = row.display_name
        self.source_url = row.source_url
        self.source_date = row.source_date
        self._row = row
        self._backend = backend

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.source_status != "verified":
            return ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status=f"source {self._row.source_status}; installer blocked",
                source_url=self.source_url,
                source_date=self.source_date,
                action_needed=self._row.notes or self._row.audia_action,
            )
        if not self._row.status_command:
            return ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status="no status probe available",
                source_url=self.source_url,
                source_date=self.source_date,
                action_needed=self._row.audia_action,
            )
        try:
            cmd = _parameterize_command(self._row.status_command, self._backend)
            parts = _command_parts(cmd)
            probe = CommandProbe(tuple(parts), expect_exit=0, timeout=15)
            result = probe.check()
            state = RecipeState.VERIFIED if result.passed else RecipeState.ABSENT
            return ProviderRecipeResult.ok(
                state,
                status=result.detail,
                source_url=self.source_url,
                source_date=self.source_date,
                action_needed=self._row.audia_action,
            )
        except Exception as exc:
            return ProviderRecipeResult.fail(
                str(exc),
                source_url=self.source_url,
                action_needed=self._row.audia_action,
            )

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.source_status != "verified":
            return ProviderRecipeResult.fail(
                f"installer source {self._row.source_status}; refusing to execute",
                source_url=self.source_url,
                action_needed=self._row.notes or self._row.audia_action,
            )
        if not self._row.install_command:
            return ProviderRecipeResult.fail(
                "no install command for this provider",
                source_url=self.source_url,
                action_needed=self._row.audia_action,
            )
        try:
            cmd = _parameterize_command(self._row.install_command, self._backend)
            parts = _command_parts(cmd)
            proc = subprocess.run(
                parts, capture_output=True, text=True, timeout=60, check=False
            )
            if proc.returncode == 0:
                return ProviderRecipeResult.ok(
                    RecipeState.INSTALLING,
                    status="installer command succeeded",
                    source_url=self.source_url,
                    source_date=self.source_date,
                )
            return ProviderRecipeResult.fail(
                f"installer failed: {proc.stderr.strip()}",
                source_url=self.source_url,
                action_needed=self._row.audia_action,
            )
        except Exception as exc:
            return ProviderRecipeResult.fail(
                str(exc),
                source_url=self.source_url,
                action_needed=self._row.audia_action,
            )

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.CONFIGURING,
            status="hooks installed via CLI; no config write needed",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.probe(context)

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.source_status != "verified":
            return ProviderRecipeResult.ok(
                RecipeState.ABSENT,
                status=f"source {self._row.source_status}; no installer was executed",
                source_url=self.source_url,
                source_date=self.source_date,
                action_needed=self._row.notes or self._row.audia_action,
            )
        if not self._row.uninstall_command:
            return ProviderRecipeResult.fail(
                "no uninstall command for this provider",
                source_url=self.source_url,
                action_needed=self._row.audia_action,
            )
        try:
            cmd = _parameterize_command(self._row.uninstall_command, self._backend)
            parts = _command_parts(cmd)
            proc = subprocess.run(
                parts, capture_output=True, text=True, timeout=60, check=False
            )
            if proc.returncode == 0:
                return ProviderRecipeResult.ok(
                    RecipeState.ABSENT,
                    status="uninstaller command succeeded",
                    source_url=self.source_url,
                    source_date=self.source_date,
                )
            return ProviderRecipeResult.fail(
                f"uninstaller failed: {proc.stderr.strip()}",
                source_url=self.source_url,
                action_needed=self._row.audia_action,
            )
        except Exception as exc:
            return ProviderRecipeResult.fail(
                str(exc),
                source_url=self.source_url,
                action_needed=self._row.audia_action,
            )

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="hooks managed by CLI; no config to prune",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status=f"would run: {self._row.install_command} (dry-run)",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )


class PluginConfigRecipe:
    """Plugin-config recipe: writes plugin registration to provider config.

    For providers like OpenCode, Claude that use plugin arrays or marketplace.
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        backend: HindsightBackendConfig,
        target: HindsightTarget | None = None,
    ) -> None:
        self.provider_id = row.provider_id
        self.capability_id = "hindsight"
        self.backend_id = None
        self.recipe_kind = row.recipe_kind
        self.display_name = row.display_name
        self.source_url = row.source_url
        self.source_date = row.source_date
        self._row = row
        self._backend = backend
        self._target = target
        self._inner = None
        if target:
            self._inner = HindsightMcpRecipe(backend, target)

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._inner:
            result = self._inner.probe(context)
            return ProviderRecipeResult(
                success=result.success,
                state=result.state,
                artifacts_owned=list(result.artifacts_owned),
                status=result.status,
                source_url=self.source_url,
                source_date=self.source_date,
                action_needed=self._row.audia_action,
            )
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="plugin config managed by CLI",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.install_command:
            if self._row.source_status != "verified":
                return ProviderRecipeResult.fail(
                    f"plugin installer source {self._row.source_status}; refusing to execute",
                    source_url=self.source_url,
                    action_needed=self._row.notes or self._row.audia_action,
                )
            try:
                cmd = _parameterize_command(self._row.install_command, self._backend)
                parts = _command_parts(cmd)
                proc = subprocess.run(
                    parts, capture_output=True, text=True, timeout=60, check=False
                )
                if proc.returncode != 0:
                    return ProviderRecipeResult.fail(
                        f"plugin install failed: {proc.stderr.strip()}",
                        source_url=self.source_url,
                        action_needed=self._row.audia_action,
                    )
            except Exception as exc:
                return ProviderRecipeResult.fail(
                    str(exc),
                    source_url=self.source_url,
                    action_needed=self._row.audia_action,
                )
        return ProviderRecipeResult.ok(
            RecipeState.INSTALLING,
            status="plugin installed",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._inner:
            result = self._inner.configure(context)
            return ProviderRecipeResult(
                success=result.success,
                state=result.state,
                artifacts_owned=list(result.artifacts_owned),
                status=result.status,
                source_url=self.source_url,
                source_date=self.source_date,
                action_needed=self._row.audia_action,
            )
        return ProviderRecipeResult.ok(
            RecipeState.CONFIGURING,
            status="plugin config applied",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._inner:
            result = self._inner.verify(context)
            return ProviderRecipeResult(
                success=result.success,
                state=result.state,
                artifacts_owned=list(result.artifacts_owned),
                status=result.status,
                error=result.error,
                source_url=self.source_url,
                source_date=self.source_date,
                action_needed=self._row.audia_action,
            )
        return ProviderRecipeResult.ok(
            RecipeState.VERIFIED,
            status="plugin verified",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._row.uninstall_command:
            if self._row.source_status != "verified":
                return ProviderRecipeResult.ok(
                    RecipeState.ABSENT,
                    status=f"source {self._row.source_status}; no plugin installer was executed",
                    source_url=self.source_url,
                    source_date=self.source_date,
                    action_needed=self._row.notes or self._row.audia_action,
                )
            try:
                cmd = _parameterize_command(self._row.uninstall_command, self._backend)
                parts = _command_parts(cmd)
                proc = subprocess.run(
                    parts, capture_output=True, text=True, timeout=60, check=False
                )
                if proc.returncode != 0:
                    return ProviderRecipeResult.fail(
                        f"plugin uninstall failed: {proc.stderr.strip()}",
                        source_url=self.source_url,
                        action_needed=self._row.audia_action,
                    )
            except Exception as exc:
                return ProviderRecipeResult.fail(
                    str(exc),
                    source_url=self.source_url,
                    action_needed=self._row.audia_action,
                )
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="plugin uninstalled",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        if self._inner:
            result = self._inner.prune(context)
            return ProviderRecipeResult(
                success=result.success,
                state=result.state,
                artifacts_owned=list(result.artifacts_owned),
                status=result.status,
                error=result.error,
                source_url=self.source_url,
                source_date=self.source_date,
                action_needed=self._row.audia_action,
            )
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="nothing to prune",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="would install plugin (dry-run)",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )


class GuidanceOnlyRecipe:
    """Guidance-only recipe: no automation, action-needed guidance only.

    For providers with no official Hindsight integration yet.
    """

    def __init__(self, row: HindsightRecipeRow) -> None:
        self.provider_id = row.provider_id
        self.capability_id = "hindsight"
        self.backend_id = None
        self.recipe_kind = ProviderRecipeKind.GUIDANCE_ONLY
        self.display_name = row.display_name
        self.source_url = row.source_url
        self.source_date = row.source_date
        self._row = row

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="no automated integration available",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.notes or "manual setup required",
        )

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.fail(
            "no automated install for this provider",
            source_url=self.source_url,
            action_needed=self._row.notes or "manual setup required",
        )

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.install(context)

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.probe(context)

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="nothing to uninstall",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return ProviderRecipeResult.ok(
            RecipeState.ABSENT,
            status="nothing to prune",
            source_url=self.source_url,
            source_date=self.source_date,
        )

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.probe(context)


def _parameterize_command(
    command: str,
    backend: HindsightBackendConfig,
) -> str:
    """Replace placeholder tokens in install/uninstall/status commands with backend values.

    Supported placeholders:
      URL    → backend.base_url
      TOKEN  → backend.api_key
      KEY    → backend.api_key
      ID     → backend.bank_id
    """
    if not command:
        return command
    replacements = [
        ("URL", backend.base_url),
    ]
    if backend.api_key:
        replacements.extend([
            ("TOKEN", backend.api_key),
            ("KEY", backend.api_key),
        ])
    if backend.bank_id:
        replacements.append(("ID", backend.bank_id))
    for placeholder, value in replacements:
        command = command.replace(placeholder, value)
    return command


def _platform_supported(row: HindsightRecipeRow) -> bool:
    """Check if the current platform is in the row's platform constraints.

    Uses the canonical platform_key() from foundation.toolchains.
    """
    if not row.platform_constraints:
        return True
    from audiagentic.foundation.toolchains import platform_key
    current = platform_key()
    for constraint in row.platform_constraints:
        constraint_lower = constraint.lower()
        if "macos" in constraint_lower or "darwin" in constraint_lower:
            if current == "darwin":
                return True
        elif "linux" in constraint_lower:
            if current == "linux":
                return True
        elif "win" in constraint_lower:
            if current == "win":
                return True
    return False


def resolve_hindsight_strategy(
    provider_id: str,
    project_root: Path | None = None,
) -> HindsightRecipeRow | None:
    """Resolve the best Hindsight strategy for a provider.

    Precedence: verified native/launch-wrapper > mcp-config > fallback-mcp > rules-only.
    Platform gate drops unsupported strategies and falls back.
    Source gate blocks unverified native/launch-wrapper commands (enforced by builder).
    """
    rows = [row for row in HINDSIGHT_RECIPE_MATRIX if row.provider_id == provider_id]
    if not rows:
        return None

    row = rows[0]  # one row per provider

    # Platform gate: if native strategy is platform-gated, fall back
    if not _platform_supported(row):
        if row.recipe_kind in (ProviderRecipeKind.HOOKS, ProviderRecipeKind.WRAPPER_CLI,
                                ProviderRecipeKind.PLUGIN_CONFIG):
            # Check if provider has MCP config support for fallback
            descriptor = get_descriptor(provider_id)
            if descriptor and descriptor.mcp_config:
                return HindsightRecipeRow(
                    provider_id=provider_id,
                    display_name=row.display_name,
                    integration_type="fallback-mcp",
                    recipe_kind=ProviderRecipeKind.MCP_CONFIG,
                    source_url=row.source_url,
                    source_date=row.source_date,
                    source_status="unconfirmed",
                    audia_action="manage_config_writes",
                    notes=(f"platform-gated native ({', '.join(row.platform_constraints)}); "
                           "fallback to MCP config"),
                )
            # No MCP fallback available → rules-only
            return HindsightRecipeRow(
                provider_id=provider_id,
                display_name=row.display_name,
                integration_type="rules-only",
                recipe_kind=ProviderRecipeKind.GUIDANCE_ONLY,
                source_url=row.source_url,
                source_date=row.source_date,
                source_status="unconfirmed",
                audia_action="action_needed",
                notes=(f"platform-gated ({', '.join(row.platform_constraints)}); "
                       "rules-only fallback"),
            )

    return row


def build_hindsight_recipe(
    row: HindsightRecipeRow,
    backend: HindsightBackendConfig,
    provider_id: str,
    project_root: Path | None = None,
) -> Any:
    """Build a recipe object for a resolved Hindsight strategy row.

    Source gate: refuses to build executable recipes for native-installer/
    launch-wrapper when source_status is not 'verified'.
    """
    harness_path = _resolve_harness_config_path(provider_id, project_root)

    # Source gate for native/launch-wrapper
    if row.recipe_kind in (ProviderRecipeKind.HOOKS, ProviderRecipeKind.WRAPPER_CLI):
        if row.source_status != "verified":
            return GuidanceOnlyRecipe(row)
        return HooksInstallerRecipe(row, backend)

    if row.recipe_kind == ProviderRecipeKind.PLUGIN_CONFIG:
        if row.source_status != "verified" and row.install_command:
            return GuidanceOnlyRecipe(row)
        if harness_path:
            target = HindsightTarget(config_path=harness_path)
            return PluginConfigRecipe(row, backend, target)
        return GuidanceOnlyRecipe(row)

    if row.recipe_kind in (ProviderRecipeKind.MCP_CONFIG, ProviderRecipeKind.HYBRID):
        if harness_path:
            target = HindsightTarget(config_path=harness_path)
            inner = HindsightMcpRecipe(backend, target)
            return _McpConfigAdapter(row, inner)
        return GuidanceOnlyRecipe(row)

    if row.recipe_kind == ProviderRecipeKind.GUIDANCE_ONLY:
        return GuidanceOnlyRecipe(row)

    return GuidanceOnlyRecipe(row)


def _resolve_harness_config_path(provider_id: str, project_root: Path | None = None) -> str | None:
    """Resolve the real harness config path for a provider from its descriptor."""
    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        return None
    spec = descriptor.mcp_config
    if spec is None:
        return None
    config_path = spec.config_path
    if callable(config_path):
        resolved = config_path(project_root)
        return str(resolved)
    return str(config_path)


def register_hindsight_recipes(
    registry: ProviderRecipeRegistry,
    backend: HindsightBackendConfig | None = None,
    project_root: Path | None = None,
) -> list[Any]:
    """Register Hindsight recipes for providers that have matrix rows.

    Uses resolve_hindsight_strategy + build_hindsight_recipe for each provider.
    Applies platform gate and source gate automatically.
    Returns the list of registered recipes.
    """
    if backend is None and project_root:
        backend = build_hindsight_backend(project_root)

    registered: list[Any] = []

    for row in HINDSIGHT_RECIPE_MATRIX:
        resolved = resolve_hindsight_strategy(row.provider_id, project_root)
        if resolved is None:
            continue

        if not backend:
            recipe = GuidanceOnlyRecipe(resolved)
        else:
            recipe = build_hindsight_recipe(resolved, backend, resolved.provider_id, project_root)

        registry.register(recipe)
        registered.append(recipe)

    return registered


class _McpConfigAdapter:
    """Thin adapter that wraps HindsightMcpRecipe with provider metadata."""

    def __init__(
        self,
        row: HindsightRecipeRow,
        inner: HindsightMcpRecipe,
    ) -> None:
        self.provider_id = row.provider_id
        self.capability_id = "hindsight"
        self.backend_id = None
        self.recipe_kind = row.recipe_kind
        self.display_name = row.display_name
        self.source_url = row.source_url
        self.source_date = row.source_date
        self._inner = inner
        self._row = row

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = self._inner.probe(context)
        return ProviderRecipeResult(
            success=result.success,
            state=result.state,
            artifacts_owned=list(result.artifacts_owned),
            status=result.status,
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = self._inner.install(context)
        return ProviderRecipeResult(
            success=result.success,
            state=result.state,
            artifacts_owned=list(result.artifacts_owned),
            status=result.status,
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = self._inner.configure(context)
        return ProviderRecipeResult(
            success=result.success,
            state=result.state,
            artifacts_owned=list(result.artifacts_owned),
            status=result.status,
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = self._inner.verify(context)
        return ProviderRecipeResult(
            success=result.success,
            state=result.state,
            artifacts_owned=list(result.artifacts_owned),
            status=result.status,
            error=result.error,
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = self._inner.uninstall(context)
        return ProviderRecipeResult(
            success=result.success,
            state=result.state,
            artifacts_owned=list(result.artifacts_owned),
            status=result.status,
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = self._inner.prune(context)
        return ProviderRecipeResult(
            success=result.success,
            state=result.state,
            artifacts_owned=list(result.artifacts_owned),
            status=result.status,
            error=result.error,
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        result = self._inner.probe(context)
        state = RecipeState.VERIFIED if (result.success and result.state is RecipeState.VERIFIED) else RecipeState.ABSENT
        return ProviderRecipeResult.ok(
            state,
            status="already provisioned (dry-run)" if state is RecipeState.VERIFIED else "would install (dry-run)",
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )

    def to_result(self, base) -> ProviderRecipeResult:
        return ProviderRecipeResult(
            success=base.success,
            state=base.state,
            artifacts_owned=list(base.artifacts_owned),
            status=base.status,
            error=base.error,
            details=dict(base.details),
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=self._row.audia_action,
        )


def build_hindsight_status(
    registry: ProviderRecipeRegistry,
    provider_id: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build Hindsight status for a specific provider from the recipe registry."""
    recipes = registry.list_for_provider(provider_id, "hindsight")
    if not recipes:
        return {
            "provider_id": provider_id,
            "hindsight": {
                "status": "not_registered",
                "action_needed": "no Hindsight recipe for this provider",
            },
        }

    results = []
    for recipe in recipes:
        status = registry.status(
            recipe.provider_id,
            recipe.capability_id,
            recipe.backend_id,
            context,
        )
        if status is not None:
            results.append({
                "provider_id": recipe.provider_id,
                "capability_id": recipe.capability_id,
                "kind": recipe.recipe_kind.value,
                "state": status.state.value,
                "status": status.status,
                "action_needed": status.action_needed,
                "source_url": status.source_url,
            })

    return {
        "provider_id": provider_id,
        "hindsight": {
            "status": "active" if any(r["state"] == "verified" for r in results) else "inactive",
            "recipes": results,
        },
    }


__all__ = [
    "GuidanceOnlyRecipe",
    "HooksInstallerRecipe",
    "PluginConfigRecipe",
    "build_hindsight_status",
    "register_hindsight_recipes",
]
