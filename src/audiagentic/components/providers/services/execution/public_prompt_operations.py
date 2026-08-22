"""Provider-owned prompt metadata and narrow one-shot operations.

Requester components use these operations through ``providers_api``.  The
module keeps tag/descriptors, runtime configuration and adapter dispatch in
the providers component while exposing only the semantic data agent-jobs
needs to parse and launch a prompt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def list_canonical_provider_ids() -> tuple[str, ...]:
    """Return the provider ids accepted by provider-backed launches."""
    from audiagentic.components.providers.descriptors.registry import canonical_provider_ids

    return canonical_provider_ids()


def get_prompt_syntax_defaults() -> dict[str, Any]:
    """Build provider-owned defaults for the shared prompt syntax document."""
    from audiagentic.components.providers.descriptors.registry import (
        all_descriptors,
        provider_alias_map,
    )
    from audiagentic.components.providers.tags.registry import all_tags

    tags = all_tags()
    canonical_tags = sorted(tags)
    tag_aliases: dict[str, str] = {}
    for tag_id, descriptor in tags.items():
        tag_aliases[tag_id] = tag_id
        tag_aliases.update({alias: tag_id for alias in descriptor.aliases})

    generic_tag = next((tag_id for tag_id, item in tags.items() if item.is_generic_tag), None)
    review_tag = next((tag_id for tag_id, item in tags.items() if item.is_review_tag), None)
    implement_tag = next(
        (
            tag_id
            for tag_id, item in tags.items()
            if not item.is_generic_tag and not item.is_review_tag and "implement" in tag_id
        ),
        canonical_tags[0] if canonical_tags else "adhoc",
    )
    skill_surfaces = {
        provider_id: {"renderer": provider_id, "path": descriptor.skill_surface_path}
        for provider_id, descriptor in all_descriptors().items()
        if descriptor.skill_surface_path
    }
    return {
        "contract-version": "v1",
        "default-profile": "shared",
        "generic-tag": generic_tag or "adhoc",
        "no-body-required-tags": [tag_id for tag_id, item in tags.items() if not item.requires_body],
        "review-tag": review_tag or "adhoc",
        "implement-tag": implement_tag,
        "canonical-tags": canonical_tags,
        "tag-aliases": tag_aliases,
        "skill-surfaces": skill_surfaces,
        "provider-aliases": provider_alias_map(),
    }


def get_provider_prompt_settings_profile(project_root: Path, provider_id: str) -> str | None:
    """Return the optional prompt-syntax profile selected by one provider."""
    from ..config.provider_config import load_provider_config

    providers = load_provider_config(project_root).get("providers") or {}
    provider_config = providers.get(provider_id, {}) if isinstance(providers, dict) else {}
    prompt_surface = provider_config.get("prompt-surface") if isinstance(provider_config, dict) else None
    profile = prompt_surface.get("settings-profile") if isinstance(prompt_surface, dict) else None
    return profile.strip() if isinstance(profile, str) and profile.strip() else None


def is_provider_enabled_for_launch(project_root: Path, provider_id: str) -> bool:
    """Return whether a provider is enabled for a prompt launch."""
    from ..config.provider_config import is_provider_enabled

    return is_provider_enabled(project_root, provider_id)


def resolve_launch_model(
    project_root: Path,
    *,
    provider_id: str,
    model_id: str | None,
    model_alias: str | None,
) -> dict[str, Any]:
    """Resolve one launch model using only provider-owned configuration."""
    from ..catalog.models import resolve_model_selection
    from ..config.provider_config import load_provider_config

    providers = load_provider_config(project_root).get("providers") or {}
    provider_config = providers.get(provider_id, {}) if isinstance(providers, dict) else {}
    return resolve_model_selection(
        provider_id=provider_id,
        provider_config=provider_config if isinstance(provider_config, dict) else {},
        job_request={"model-id": model_id, "model-alias": model_alias},
        catalog=None,
    )


def load_packaged_prompt_template(
    tag: str,
    *,
    template_name: str | None,
) -> tuple[str, Path | None] | None:
    """Resolve a provider-owned packaged prompt template by semantic tag."""
    from audiagentic.components.providers.tags.registry import all_tags

    descriptor = all_tags().get(tag)
    if descriptor is None and tag.startswith("ag-"):
        descriptor = all_tags().get(tag.removeprefix("ag-"))
    if descriptor is None:
        if tag in {"prompt-profile", "prompt-profiles"}:
            from .agent_prompt_profiles import load_profile_template

            profile_id = (template_name or "default").removesuffix("-with-body")
            has_body = (template_name or "default").endswith("-with-body")
            text, _, _ = load_profile_template(profile_id, has_body=has_body)
            return text, None
        return None
    requested = template_name or "default"
    for prompt in descriptor.prompts:
        if prompt.name != requested:
            continue
        source = descriptor.config_dir / prompt.content_file
        if source.exists():
            return source.read_text(encoding="utf-8"), source
        bodies = [item.body.strip() for item in descriptor.instructions if item.body.strip()]
        content = "\n\n".join(bodies) or descriptor.description or f"{descriptor.display_name} prompt"
        return content.rstrip() + "\n", None
    return None


def execute_provider_review_turn(
    project_root: Path,
    *,
    provider_id: str,
    packet_data: dict[str, Any],
) -> dict[str, Any] | None:
    """Run a review turn when the selected provider supports direct review execution.

    This is intentionally review-specific.  Gateway worker attempts use the
    stricter ``ProviderExecutionRequest`` public contract instead.
    """
    from ..config.provider_config import load_provider_config
    from .execution import execute_provider

    providers = load_provider_config(project_root).get("providers") or {}
    provider_config = providers.get(provider_id, {}) if isinstance(providers, dict) else {}
    if not isinstance(provider_config, dict) or provider_config.get("access-mode") not in {
        "cli",
        "external-configured",
        "none",
    }:
        return None
    return execute_provider(
        provider_id=provider_id,
        packet_ctx=dict(packet_data),
        provider_cfg=provider_config,
    )


__all__ = [
    "execute_provider_review_turn",
    "get_prompt_syntax_defaults",
    "get_provider_prompt_settings_profile",
    "is_provider_enabled_for_launch",
    "list_canonical_provider_ids",
    "load_packaged_prompt_template",
    "resolve_launch_model",
]
