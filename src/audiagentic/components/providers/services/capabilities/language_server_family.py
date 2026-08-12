"""Descriptor-backed language-server-projection automation family."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.language_server_projection import (
    LanguageServerProjectionMode,
    LanguageServerProjectionRequest,
    LanguageServerProjectionResult,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.foundation.toolchains.config.managed_config import (
    apply_managed_config_remove,
    apply_managed_config_write,
    resolve_managed_config_path,
)

FAMILY_ID = "language-server-projection"


def _family_declaration():
    """Resolve the language-server-projection family declaration from config."""
    from audiagentic.components.providers.descriptors.capability_catalogue import get_catalogue

    return get_catalogue().families[FAMILY_ID]


def _result(**updates: Any) -> LanguageServerProjectionResult:
    values = {"ok": True, "supported": True, **updates}
    return LanguageServerProjectionResult(**values)


def manage_language_servers(
    project_root: Path,
    provider_id: str,
    *,
    mode: LanguageServerProjectionMode,
    request: LanguageServerProjectionRequest,
) -> LanguageServerProjectionResult:
    """Reconcile typed caller-owned language server entries using descriptor capabilities."""
    descriptor = get_descriptor(provider_id)
    if (
        descriptor is None
        or descriptor.language_servers_config is None
        or descriptor.automation_capability("language-server-projection") is None
    ):
        return _result(provider_id=provider_id, ok=False, supported=False, error_code="RES-PREC-001")
    if mode not in _family_declaration().supported_modes:
        return _result(provider_id=provider_id, ok=False, error_code="CON-PREC-002")

    spec = descriptor.language_servers_config
    config_path = resolve_managed_config_path(spec, project_root)

    if mode == "status":
        try:
            current = spec.reader(config_path)
            synced = [
                lang
                for lang, entry in request.entries.items()
                if lang in current and current[lang] == entry
            ]
            return _result(
                provider_id=provider_id,
                ok=True,
                synced=tuple(sorted(synced)),
                skipped=tuple(sorted(set(request.entries) - set(synced))),
            )
        except Exception:
            return _result(provider_id=provider_id, ok=False, error_code="CON-PLSV-001")

    if mode == "apply":
        try:
            apply_managed_config_write(spec, config_path, request.entries)
            return _result(
                provider_id=provider_id,
                ok=True,
                synced=tuple(sorted(request.entries)),
            )
        except Exception:
            return _result(provider_id=provider_id, ok=False, error_code="CON-PLSV-002")

    # mode == "prune"
    try:
        pruned = []
        for lang in request.entries:
            if apply_managed_config_remove(spec, config_path, lang):
                pruned.append(lang)
        return _result(
            provider_id=provider_id,
            ok=True,
            pruned=tuple(sorted(pruned)),
        )
    except Exception:
        return _result(provider_id=provider_id, ok=False, error_code="CON-PLSV-003")


__all__ = ["manage_language_servers"]
