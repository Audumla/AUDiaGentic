"""Descriptor-driven removal of a disabled provider's project footprint."""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.components.providers.services.mcp.managed_mcp_registry import (
    mcp_ownership_registry,
)
from audiagentic.components.providers.services.mcp.mcp import (
    sync_managed_provider_mcp_subset,
)
from audiagentic.components.providers.surfaces.manager import (
    prune_provider_surfaces,
)
from audiagentic.foundation.features.state import remove_implementation_state
from audiagentic.foundation.toolchains.config.artifact_registry import ArtifactRegistry
from audiagentic.foundation.toolchains.config.managed_config import resolve_managed_config_path


def _result_ok(result: object) -> bool:
    if isinstance(result, dict):
        return bool(result.get("ok", True))
    return bool(getattr(result, "ok", True))


def purge_provider_project(project_root: Path, provider_id: str) -> dict[str, object]:
    """Remove AUDiaGentic-owned project artifacts for one disabled provider.

    Provider descriptors and ownership registries determine the targets. User
    content in shared config files is preserved; whole files are removed only
    when the artifact registry proves AUDiaGentic created them.
    """
    descriptor = get_descriptor(provider_id)
    if descriptor is None:
        return {"ok": False, "provider_id": provider_id, "error": "unknown provider"}

    results: list[object] = []
    owned = mcp_ownership_registry(project_root).load().get(provider_id, {})
    if owned and descriptor.mcp_config is not None:
        results.append(
            sync_managed_provider_mcp_subset(
                provider_id=provider_id,
                project_root=project_root,
                desired_entries={},
                managed_ids=set(owned),
            )
        )

    results.append(prune_provider_surfaces(project_root, provider_id=provider_id))

    registry = ArtifactRegistry(project_root)
    for recipe in registry.recipes():
        if recipe in {f"provider-settings/{provider_id}"} or recipe.startswith(
            f"managed-config/{provider_id}/"
        ):
            results.append(registry.prune(recipe))

    # A provider config that is empty after managed pruning carries no user
    # content and is safe to remove. Non-empty configs remain untouched.
    for spec in (
        descriptor.mcp_config,
        descriptor.language_servers_config,
        descriptor.model_config,
        descriptor.plugin_config,
        descriptor.hooks_config,
    ):
        if spec is None:
            continue
        path = resolve_managed_config_path(spec, project_root)
        if not path.exists():
            continue
        try:
            current = spec.reader(path)
        except Exception:  # noqa: BLE001 - a provider config may be foreign
            continue
        if current:
            continue
        path.unlink()
        parent = path.parent
        if parent != project_root and parent.exists() and not any(parent.iterdir()):
            parent.rmdir()

    # A managed instruction file that is now empty has no remaining project
    # value. Non-empty files are retained because they contain user content.
    for agent_file in descriptor.agent_files:
        if not agent_file.managed:
            continue
        path = project_root / agent_file.rel_path
        if path.exists() and not path.read_text(encoding="utf-8").strip():
            path.unlink()
            parent = path.parent
            if parent != project_root and parent.exists() and not any(parent.iterdir()):
                parent.rmdir()

    remove_implementation_state(project_root, "providers", provider_id)
    return {
        "ok": all(_result_ok(item) for item in results),
        "provider_id": provider_id,
        "results": results,
    }
