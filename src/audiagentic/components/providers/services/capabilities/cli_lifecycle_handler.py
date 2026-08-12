from __future__ import annotations

from pathlib import Path
from typing import Any

from audiagentic.components.providers.contracts.cli_lifecycle import CliLifecycleResult
from audiagentic.components.providers.descriptors.registry import get_descriptor

from .recipe_definitions import RecipeHandler


def _make_cli_handler(
    provider_id: str,
    project_root: Path,
) -> RecipeHandler:
    """Return a closure that dispatches CLI lifecycle modes to internal operations.

    The closure captures provider_id and project_root as invocation context.
    """

    def _handler(
        mode: str,
        payload: object,
        ownership_scope: object | None,
    ) -> object:
        descriptor = get_descriptor(provider_id)
        if descriptor is None or descriptor.cli_install is None:
            return CliLifecycleResult(
                ok=False,
                supported=False,
                state="skipped",
                error_code="RES-PREC-001",
            )

        if mode == "plan":
            return _do_plan(provider_id, descriptor)
        if mode == "apply":
            return _do_apply(provider_id, descriptor, project_root)
        if mode == "prune":
            return _do_prune(provider_id, descriptor, project_root)
        if mode == "status":
            return _do_status(provider_id, descriptor)
        if mode == "upgrade-status":
            return _do_upgrade_status(descriptor)
        if mode == "upgrade":
            return _do_upgrade(provider_id, descriptor, project_root)

        return CliLifecycleResult(
            ok=False,
            supported=False,
            state="failed",
            error_code="CON-PREC-002",
        )

    return _handler


def _do_plan(
    provider_id: str,
    descriptor: Any,
) -> CliLifecycleResult:
    """Plan: probe CLI state without mutation."""
    from ..lifecycle.lifecycle import (
        probe_provider_cli,
    )

    probe = probe_provider_cli(descriptor)
    if probe and probe.get("available"):
        return CliLifecycleResult(
            ok=True,
            supported=True,
            changed=False,
            state="installed",
        )
    return CliLifecycleResult(
        ok=True,
        supported=True,
        changed=True,
        state="uninstalled",
        action_needed="install",
    )


def _do_apply(
    provider_id: str,
    descriptor: Any,
    project_root: Path,
) -> CliLifecycleResult:
    """Apply: probe first; install if absent; no-op if present."""
    from ..lifecycle.lifecycle import (
        install_provider_cli,
        probe_provider_cli,
    )

    probe = probe_provider_cli(descriptor)
    if probe and probe.get("available"):
        return CliLifecycleResult(
            ok=True,
            supported=True,
            changed=False,
            state="installed",
        )

    result = install_provider_cli(provider_id, project_root=project_root)
    if result.get("status") in {"installed", "ok"}:
        return CliLifecycleResult(
            ok=True,
            supported=True,
            changed=True,
            state="installed",
        )

    return CliLifecycleResult(
        ok=False,
        supported=True,
        changed=False,
        state="failed",
        action_needed=result.get("reason"),
    )


def _do_prune(
    provider_id: str,
    descriptor: Any,
    project_root: Path,
) -> CliLifecycleResult:
    """Prune project-owned provider state while leaving the CLI installed."""
    from ..lifecycle.lifecycle import (
        probe_provider_cli,
    )
    from ..lifecycle.project_purge import purge_provider_project

    probe = probe_provider_cli(descriptor)
    if not probe or not probe.get("available"):
        return CliLifecycleResult(
            ok=True,
            supported=True,
            changed=False,
            state="uninstalled",
        )

    result = purge_provider_project(project_root, provider_id)
    if result.get("ok"):
        return CliLifecycleResult(
            ok=True,
            supported=True,
            changed=True,
            state="installed",
        )

    return CliLifecycleResult(
        ok=False,
        supported=True,
        changed=False,
        state="failed",
        action_needed=result.get("reason"),
    )


def _do_status(
    provider_id: str,
    descriptor: Any,
) -> CliLifecycleResult:
    """Status: probe current CLI state without mutation."""
    from ..lifecycle.lifecycle import (
        probe_provider_cli,
    )

    probe = probe_provider_cli(descriptor)
    if probe and probe.get("available"):
        return CliLifecycleResult(
            ok=True,
            supported=True,
            changed=False,
            state="installed",
        )
    return CliLifecycleResult(
        ok=True,
        supported=True,
        changed=False,
        state="uninstalled",
    )


def _do_upgrade_status(descriptor: Any) -> CliLifecycleResult:
    """Report local upgrade applicability without querying mutable upstream state."""
    from ..lifecycle.lifecycle import probe_provider_cli

    probe = probe_provider_cli(descriptor)
    if not probe or not probe.get("available"):
        return CliLifecycleResult(
            ok=True, supported=descriptor.cli_install.upgrade is not None,
            state="uninstalled", action_needed="install",
        )
    if descriptor.cli_install.upgrade is None:
        return CliLifecycleResult(
            ok=True, supported=False, state="installed",
            action_needed="no declared package-manager upgrade recipe",
        )
    return CliLifecycleResult(
        ok=True, supported=True, state="installed",
        action_needed="run explicit upgrade to reconcile through the package manager",
    )


def _do_upgrade(provider_id: str, descriptor: Any, project_root: Path) -> CliLifecycleResult:
    """Run only a descriptor-declared explicit package-manager upgrade."""
    from ..lifecycle.lifecycle import upgrade_provider_cli

    if descriptor.cli_install.upgrade is None:
        return CliLifecycleResult(
            ok=True, supported=False, state="installed",
            action_needed="no declared package-manager upgrade recipe",
        )
    result = upgrade_provider_cli(provider_id, project_root=project_root)
    if result.get("status") == "upgraded":
        return CliLifecycleResult(ok=True, supported=True, changed=True, state="installed")
    if result.get("status") == "skipped":
        return CliLifecycleResult(
            ok=True, supported=True, state="uninstalled",
            action_needed=result.get("reason"),
        )
    return CliLifecycleResult(
        ok=False, supported=True, state="failed", action_needed=result.get("reason"),
    )


__all__ = ["_make_cli_handler"]
