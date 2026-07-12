"""Hindsight provider recipe implementations.

Base + MCP-config adapter recipe classes. After SL15, the config-collapsible
kinds (GuidanceOnly, HooksInstaller) are assembled via RecipeSpec in
recipe_spec.py; this module retains _RowRecipe (provenance base), helper
functions, and genuinely-custom recipe classes (_McpConfigAdapter). Plugin
recipes live in plugin_recipes.py. Strategy selection lives in strategies.py.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from audiagentic.components.memory.hindsight.export import (
    HindsightBackendConfig,
)
from audiagentic.components.memory.hindsight.matrix import (
    HindsightRecipeRow,
)
from audiagentic.components.memory.hindsight.mcp_recipe import (
    build_hindsight_mcp_entry,
)
from audiagentic.components.providers.services.recipes import (
    ProviderCapabilityRecipe,
    ProviderRecipeKind,
    ProviderRecipeResult,
    RecipeResult,
    RecipeState,
)
from audiagentic.foundation.toolchains.provision_steps import (
    ConfigSetStep,
    ProvisionStep,
    steps_from_defs,
    substitute_params,
)

logger = logging.getLogger(__name__)


#: Managed-mcp registry id under which the hindsight entry is owned. Ownership
#: rides the same managed sync as ag-* servers, so managed tooling can see,
#: collision-check, and prune the entry; ag-* projections use subset sync and
#: never touch this id.
HINDSIGHT_MANAGED_ID = "ag-hindsight"


def _sync_hindsight_mcp_entry(
    provider_id: str,
    project_root: Path | None,
    backend: HindsightBackendConfig | None,
    *,
    remove: bool = False,
) -> dict[str, Any]:
    """Write/remove the hindsight MCP entry through the managed ownership sync."""
    from audiagentic.components.providers.services.mcp import (
        sync_managed_provider_mcp_subset,
    )

    root = Path(project_root) if project_root else Path.cwd()
    desired: dict[str, Any] = {}
    if not remove and backend is not None:
        desired[HINDSIGHT_MANAGED_ID] = (
            backend.server_name,
            build_hindsight_mcp_entry(backend),
        )
    return sync_managed_provider_mcp_subset(
        provider_id, root, desired, managed_ids={HINDSIGHT_MANAGED_ID}
    )


def _absolute_project_path(path: str | Path, project_root: Path | None = None) -> Path:
    """Resolve a path that may be relative to the caller-supplied project root.

    This is the capability-layer's deliberate addition of project-root anchoring.
    Foundation provision steps do NOT anchor to a project root — they use
    ``Path.expanduser()`` and leave relative paths as-is (the runner sets cwd).
    That function anchors relative paths against the explicitly passed
    ``project_root``, distinguishing it from foundation's expanduser-only behavior.
    See RS04/RS14 in docs/planning for the audit trail on this boundary.
    """
    target = Path(path).expanduser()
    if target.is_absolute() or project_root is None:
        return target
    return Path(project_root) / target


class _RowRecipe(ProviderCapabilityRecipe):
    """Common provider metadata + result re-stamping for Hindsight recipes.

    Extends ProviderCapabilityRecipe with Hindsight-specific provenance and
    action-guidance overlay drawn from a matrix row. Provision/teardown
    orchestration comes from the ProvisioningRecipe base, with every result
    routed through :meth:`to_result` for the provenance overlay.
    """

    capability_id = "hindsight"
    backend_id: str | None = None
    # provision_steps() on these recipes exists for matrix-step introspection
    # and dry-run tooling; configure() often does work the steps cannot
    # express (inner MCP writes, URL-config files, registry registration), so
    # execution always uses the primitive path.
    provision_via_steps = False

    def __init__(
        self,
        row: HindsightRecipeRow,
        *,
        recipe_kind: ProviderRecipeKind | None = None,
    ) -> None:
        super().__init__(
            provider_id=row.provider_id,
            capability_id="hindsight",
            recipe_kind=recipe_kind if recipe_kind is not None else row.recipe_kind,
            display_name=row.display_name,
            source_url=row.source_url,
            source_date=row.source_date,
        )
        self._row = row

    def _stamp(self, result: RecipeResult) -> ProviderRecipeResult:
        """Re-stamp any recipe result with this provider's provenance.

        The row's ``audia_action`` is the default guidance when the result
        carries none of its own. ``action_needed`` is a universal RecipeResult
        field (SL11), so it is read directly rather than defensively.
        """
        return ProviderRecipeResult(
            success=result.success,
            state=result.state,
            artifacts_owned=list(result.artifacts_owned),
            status=result.status,
            error=result.error,
            details=dict(result.details or {}),
            source_url=self.source_url,
            source_date=self.source_date,
            action_needed=result.action_needed or self._row.audia_action,
        )

    def to_result(self, base: RecipeResult) -> ProviderRecipeResult:  # type: ignore[override]
        """Convert generic result with Hindsight provenance overlay."""
        return self._stamp(base)


def _parameterize_command(
    command: str,
    backend: HindsightBackendConfig,
) -> str:
    """Replace {URL}/{MCP_URL}/{TOKEN}/{KEY}/{ID} placeholders with backend values."""
    return substitute_params(command, _hindsight_params(backend))


def _hindsight_params(backend: HindsightBackendConfig) -> dict[str, str]:
    """Build params dict from backend config for ProvisionStep placeholder substitution.

    Supported keys: URL, MCP_URL, TOKEN, KEY, ID.
    All keys are always present; optional fields (TOKEN, KEY, ID) default to ""
    so YAML steps can reference them without raising on unknown placeholders.
    ShellProvisionStep filters out --flag= args with empty values at run time.
    """
    return {
        "URL": backend.base_url,
        "MCP_URL": backend.mcp_url or "",
        "TOKEN": backend.api_key or "",
        "KEY": backend.api_key or "",
        "ID": backend.bank_id or "",
    }



class _McpConfigAdapter(_RowRecipe):
    """Thin adapter that wires MCP entry management onto provider machinery.

    Probe/verify use ``get_managed_entry_status`` (descriptor reader comparison);
    configure/prune go through the managed ownership sync so the hindsight
    entry is registered in managed-mcp-servers.json like every other
    AUDiaGentic-owned entry (HM21/RV155). Hindsight-specific residue: the
    backend config (entry payload) and managed-id ``ag-hindsight``.
    Results are re-stamped with this provider's provenance via ``_stamp``.
    """

    def __init__(
        self,
        row: HindsightRecipeRow,
        backend: HindsightBackendConfig,
        config_path: Path,
        project_root: Path | None = None,
    ) -> None:
        super().__init__(row)
        self._backend = backend
        self._server_name = backend.server_name
        self._entry = build_hindsight_mcp_entry(backend)
        self._config_path = config_path
        self._project_root = project_root

    def _mcp_status(self) -> dict[str, Any]:
        """Look up the entry status via provider machinery."""
        from audiagentic.components.providers.services.mcp import (
            get_managed_entry_status,
        )

        return get_managed_entry_status(
            self.provider_id,
            Path(self._project_root) if self._project_root else Path.cwd(),
            self._server_name,
            self._entry,
        )

    def provision_steps(self) -> list[ProvisionStep]:
        params = _hindsight_params(self._backend)
        steps: list[ProvisionStep] = []
        # Row-level install/uninstall steps from matrix (e.g. pip install + init)
        if self._row.install_steps:
            steps.extend(steps_from_defs(
                self._row.install_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        # Row-level configure steps (e.g. config-set for plugin arrays)
        if self._row.configure_steps:
            steps.extend(steps_from_defs(
                self._row.configure_steps, params,
                recipe_id=f"hindsight-{self.provider_id}",
            ))
        # MCP config step rebuilt from data (introspection-only; keeps hybrid test green)
        steps.append(ConfigSetStep(
            id=f"config-entry-{self._server_name}",
            path=str(self._config_path),
            key_path=("mcpServers", self._server_name),
            value=self._entry,
            recipe_id=f"hindsight:{self.provider_id}:mcp",
        ))
        return steps

    def probe(self, context: dict[str, Any]) -> ProviderRecipeResult:
        status = self._mcp_status()
        if not status["ok"]:
            # No mcp_config defined → treat as absent (never crash)
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.ABSENT, status="entry absent",
            ))
        state = (
            RecipeState.VERIFIED if status["matches"] else RecipeState.ABSENT
        )
        return self._stamp(ProviderRecipeResult.ok(
            state,
            artifacts=[f"{self._config_path}::{self._server_name}"]
            if status["present"] else [],
            status="entry present" if status["present"] else "entry absent",
        ))

    def install(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.INSTALLING, status="external backend",
        ))

    def configure(self, context: dict[str, Any]) -> ProviderRecipeResult:
        sync = _sync_hindsight_mcp_entry(
            self.provider_id, self._project_root, self._backend
        )
        if not sync.get("ok"):
            return self._stamp(ProviderRecipeResult.fail(
                f"managed MCP sync refused: {sync.get('collisions')}",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.CONFIGURING,
            artifacts=[f"{sync.get('config_path')}::{self._server_name}"],
            status="entry written (managed)",
        ))

    def verify(self, context: dict[str, Any]) -> ProviderRecipeResult:
        status = self._mcp_status()
        if not status["ok"]:
            return self._stamp(ProviderRecipeResult.fail("no mcp_config for this provider"))
        if status["matches"]:
            return self._stamp(ProviderRecipeResult.ok(
                RecipeState.VERIFIED,
                artifacts=[f"{self._config_path}::{self._server_name}"],
            ))
        return self._stamp(ProviderRecipeResult.fail(
            f"verify failed: entry {status['reason']}",
        ))

    def uninstall(self, context: dict[str, Any]) -> ProviderRecipeResult:
        return self.prune(context)

    def prune(self, context: dict[str, Any]) -> ProviderRecipeResult:
        sync = _sync_hindsight_mcp_entry(
            self.provider_id, self._project_root, self._backend, remove=True
        )
        if not sync.get("ok"):
            return self._stamp(ProviderRecipeResult.fail(
                f"managed MCP prune refused: {sync.get('collisions')}",
            ))
        return self._stamp(ProviderRecipeResult.ok(
            RecipeState.ABSENT, status="entry removed (managed)",
        ))

    def dry_run(self, context: dict[str, Any]) -> ProviderRecipeResult:
        status = self._mcp_status()
        verified = status["ok"] and status["matches"]
        state = RecipeState.VERIFIED if verified else RecipeState.ABSENT
        return self._stamp(ProviderRecipeResult.ok(
            state,
            status="already provisioned (dry-run)" if verified else "would install (dry-run)",
        ))

    def to_result(self, base) -> ProviderRecipeResult:
        return self._stamp(base)


__all__ = [
    "HINDSIGHT_MANAGED_ID",
]
