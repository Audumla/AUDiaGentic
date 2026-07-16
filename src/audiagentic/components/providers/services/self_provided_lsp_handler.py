"""Per-provider self-provided LSP handler (Pattern A — explicit code registration)."""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.self_provided_lsp import (
    SelfProvidedLspMode,
    SelfProvidedLspResult,
)
from audiagentic.components.providers.descriptors.registry import get_descriptor
from audiagentic.foundation.logging.redaction import redact_text


def _make_self_provided_lsp_handler(
    provider_id: str, project_root: Path
) -> Any:
    """Factory that binds project_root and returns a RecipeHandler-compatible closure."""
    return partial(_handler_impl, provider_id=provider_id, project_root=project_root)


def _hook_outcome(provider_id: str, result: object) -> SelfProvidedLspResult:
    """Map a provider hook/probe result dict onto the typed family result."""
    if not isinstance(result, dict):
        return SelfProvidedLspResult(
            ok=False, supported=True, provider_id=provider_id, error_code="CON-PSLS-003"
        )
    ok = bool(result.get("ok"))
    action_needed = result.get("action_needed") or result.get("skipped")
    if not ok and action_needed is None:
        # OU01 will move redaction to the egress boundary and delete this call.
        # Until that boundary EXISTS, this stays: hook stdout/stderr carries
        # provider output that can contain credentials, and action_needed is
        # user-facing. Removing it now leaves the value unguarded at every
        # destination. See OU01 step ordering.
        detail = result.get("error") or result.get("stderr") or result.get("stdout")
        action_needed = redact_text(str(detail)) if detail else None
    return SelfProvidedLspResult(
        ok=True,
        supported=True,
        provider_id=provider_id,
        state="provisioned" if ok else "needs-action",
        action_needed=action_needed,
    )


def _handler_impl(
    mode: SelfProvidedLspMode,
    payload: object,
    ownership_scope: object | None,
    *,
    provider_id: str,
    project_root: Path,
) -> SelfProvidedLspResult:
    """Execute one self-provided LSP operation for a specific provider.

    ``status`` is a query and never provisions: it reads the descriptor's
    non-mutating ``lsp_support_probe``. ``apply`` runs the mutating
    ``on_lsp_enabled`` hook. Mode membership is enforced against the provider's
    declaration by ProviderAutomationRegistry.dispatch before this runs.
    """
    descriptor = get_descriptor(provider_id)
    if descriptor is None or descriptor.on_lsp_enabled is None:
        return SelfProvidedLspResult(
            ok=False, supported=False, provider_id=provider_id, error_code="RES-PREC-001"
        )

    if mode == "status":
        probe = descriptor.lsp_support_probe
        if probe is None:
            # Evidence-only: without a non-mutating probe this provider cannot be
            # queried without provisioning, so report unknown rather than mutate.
            return SelfProvidedLspResult(
                ok=True,
                supported=True,
                provider_id=provider_id,
                state="unknown",
                action_needed=(
                    "provider declares no lsp_support_probe; "
                    "run apply to provision self-provided LSP support"
                ),
            )
        operation, error_code = probe, "CON-PSLS-001"
    else:
        operation, error_code = descriptor.on_lsp_enabled, "CON-PSLS-002"

    try:
        return _hook_outcome(provider_id, operation(project_root))
    except Exception as exc:  # noqa: BLE001
        return SelfProvidedLspResult(
            ok=False,
            supported=True,
            provider_id=provider_id,
            error_code=error_code,
            action_needed=redact_text(str(exc)),
        )


__all__ = ["_make_self_provided_lsp_handler"]
