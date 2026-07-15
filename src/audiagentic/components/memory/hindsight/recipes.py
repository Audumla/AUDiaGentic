"""Shared Hindsight recipe base and parameter helpers."""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.matrix import HindsightRecipeRow
from audiagentic.components.providers.services.recipes import (
    ProviderCapabilityRecipe,
    ProviderRecipeKind,
    ProviderRecipeResult,
    RecipeResult,
)


def _absolute_project_path(path: str | Path, project_root: Path | None = None) -> Path:
    """Resolve a relative artifact path against caller project root."""
    target = Path(path).expanduser()
    if target.is_absolute() or project_root is None:
        return target
    return Path(project_root) / target


class _RowRecipe(ProviderCapabilityRecipe):
    """Common provider metadata and Hindsight provenance overlay."""

    capability_id = "hindsight"
    backend_id: str | None = None
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
        return self._stamp(base)


def _parameterize_command(command: str, backend: HindsightBackendConfig) -> str:
    return _lenient_substitute(command, _hindsight_params(backend))


def _lenient_substitute(text: str, params: dict[str, str]) -> str:
    for key, value in params.items():
        text = text.replace(f"{{{key}}}", value)
    return text


def _hindsight_params(backend: HindsightBackendConfig) -> dict[str, str]:
    return {
        "URL": backend.base_url,
        "MCP_URL": backend.mcp_url or "",
        "TOKEN": backend.api_key or "",
        "KEY": backend.api_key or "",
        "ID": backend.bank_id or "",
    }


__all__: list[str] = []
