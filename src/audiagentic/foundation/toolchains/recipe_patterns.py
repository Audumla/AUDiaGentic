"""Reusable install-recipe patterns.

Data-parameterized :class:`ProvisioningRecipe` implementations for the install
shapes that recur across capabilities — declared-step installation and no-
automation integrations. Any component that installs code (toolchains, component
dependencies, capabilities) can reuse these without re-deriving the lifecycle.

Deliberately domain-neutral (Std §1): no capability vocabulary appears in the
public API — callers inject steps or payloads. Returns plain :class:`RecipeResult`;
provenance overlays happen at the caller's result boundary, not here. The module
imports nothing from the components layer.

SL13 A6: ManagedEntryRecipe and ConfigEntryTarget were removed — zero consumers
post rewire to provider MCP machinery. DeclaredStepRecipe and NoAutomationRecipe
remain as multi-consumer foundation patterns.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from audiagentic.foundation.steps import (
    build_steps_from_defs,
    lenient_substitute,
)

from .probes import CommandProbe, safe_command_parts
from .recipe_contract import ProvisioningRecipe, RecipeResult, RecipeState, run_steps

# ---------------------------------------------------------------------------
# No-automation guidance
# ---------------------------------------------------------------------------

@dataclass
class NoAutomationRecipe(ProvisioningRecipe):
    """Recipe for an integration with no automation — guidance only.

    Every lifecycle op is a clean no-op that surfaces user guidance via
    ``action_needed``. Provisioning is a successful skip (nothing to do), not a
    failure; ``install`` fails because there is nothing to automate. Reusable by
    any capability that must report "a human sets this up" without executing.
    """

    action_needed: str = ""
    absent_status: str = "no automated integration available"
    skip_status: str = "skipped: no automated integration for this provider"
    install_error: str = "no automated install for this provider"

    def __post_init__(self) -> None:
        super().__init__()

    def provision(self, context: dict[str, Any]) -> RecipeResult:
        """Override provision to always skip — this recipe has no automation."""
        return RecipeResult.ok(
            RecipeState.ABSENT, status=self.skip_status, action_needed=self.action_needed
        )

    def probe(self, context: dict[str, Any]) -> RecipeResult:
        return RecipeResult.ok(
            RecipeState.ABSENT, status=self.absent_status, action_needed=self.action_needed
        )

    def install(self, context: dict[str, Any]) -> RecipeResult:
        return RecipeResult.fail(self.install_error, action_needed=self.action_needed)

    def configure(self, context: dict[str, Any]) -> RecipeResult:
        return self.install(context)

    def verify(self, context: dict[str, Any]) -> RecipeResult:
        return self.probe(context)

    def uninstall(self, context: dict[str, Any]) -> RecipeResult:
        return RecipeResult.ok(RecipeState.ABSENT, status="nothing to uninstall")

    def prune(self, context: dict[str, Any]) -> RecipeResult:
        return RecipeResult.ok(RecipeState.ABSENT, status="nothing to prune")


# ---------------------------------------------------------------------------
# Declared-step installer
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InstallManifest:
    """Declarative install/uninstall steps behind a source-verification gate.

    Steps are provision-step dicts (shell/config/write) run with compensating
    rollback. The gate lets a recipe refuse to execute steps from an
    unverified/untrusted source. ``source_label`` is the human word for the
    current verification state (e.g. "unconfirmed"), used only in messages.
    """

    install_steps: tuple[dict[str, Any], ...] = ()
    uninstall_steps: tuple[dict[str, Any], ...] = ()
    status_command: str = ""
    verified: bool = True
    source_label: str = ""
    gate_action: str = ""
    recipe_id: str | None = None


class DeclaredStepRecipe(ProvisioningRecipe):
    """Install/uninstall/verify an integration described by declared steps.

    The canonical "install via declared steps" recipe: any component that
    installs via shell/config/write steps behind a "run only if the source is
    verified" gate, with an optional status-command probe, can reuse this. The
    caller supplies an :class:`InstallManifest`, a ``params`` dict for ``{KEY}``
    substitution, and a ``subject`` noun for messages ("installer", "plugin
    installer", ...).
    """

    def __init__(self, manifest: InstallManifest, params: dict[str, str], *, subject: str = "installer") -> None:
        super().__init__()
        self._m = manifest
        self._params = dict(params)
        self._subject = subject

    def probe(self, context: dict[str, Any]) -> RecipeResult:
        if not self._m.verified:
            return RecipeResult.ok(
                RecipeState.ABSENT,
                status=f"source {self._m.source_label}; {self._subject} blocked",
                action_needed=self._m.gate_action,
            )
        if not self._m.status_command:
            return RecipeResult.ok(RecipeState.ABSENT, status="no status probe available")
        try:
            cmd = lenient_substitute(self._m.status_command, self._params)
            result = CommandProbe(tuple(safe_command_parts(cmd)), expect_exit=0, timeout=15).check()
        except Exception as exc:  # noqa: BLE001 - report probe failure, do not crash
            return RecipeResult.fail(f"{self._subject} probe failed: {exc}")
        return RecipeResult.ok(
            RecipeState.VERIFIED if result.passed else RecipeState.ABSENT, status=result.detail
        )

    def install(self, context: dict[str, Any]) -> RecipeResult:
        if not self._m.verified:
            return RecipeResult.fail(
                f"{self._subject} source {self._m.source_label}; refusing to execute",
                action_needed=self._m.gate_action,
            )
        if not self._m.install_steps:
            return RecipeResult.fail(f"no install steps for this {self._subject}")
        steps = build_steps_from_defs(list(self._m.install_steps), self._params, recipe_id=self._m.recipe_id)
        return run_steps(
            steps, context,
            ok_state=RecipeState.INSTALLING, ok_status=f"{self._subject} succeeded",
            fail_prefix=f"{self._subject} failed",
        )

    def configure(self, context: dict[str, Any]) -> RecipeResult:
        return RecipeResult.ok(RecipeState.CONFIGURING, status="no config write needed")

    def verify(self, context: dict[str, Any]) -> RecipeResult:
        if not self._m.status_command:
            return RecipeResult.ok(
                RecipeState.VERIFIED, status=f"{self._subject} completed; no status probe available"
            )
        return self.probe(context)

    def uninstall(self, context: dict[str, Any]) -> RecipeResult:
        if not self._m.verified:
            return RecipeResult.ok(
                RecipeState.ABSENT,
                status=f"source {self._m.source_label}; no {self._subject} was executed",
                action_needed=self._m.gate_action,
            )
        if not self._m.uninstall_steps:
            return RecipeResult.fail(f"no uninstall steps for this {self._subject}")
        steps = build_steps_from_defs(list(self._m.uninstall_steps), self._params, recipe_id=self._m.recipe_id)
        return run_steps(
            steps, context,
            ok_state=RecipeState.ABSENT, ok_status="uninstaller succeeded",
            fail_prefix="uninstaller failed",
        )

    def prune(self, context: dict[str, Any]) -> RecipeResult:
        return RecipeResult.ok(RecipeState.ABSENT, status="nothing to prune")

    def provision_steps(self) -> list[Any]:
        return build_steps_from_defs(list(self._m.install_steps), self._params, recipe_id=self._m.recipe_id)


__all__ = [
    "DeclaredStepRecipe",
    "InstallManifest",
    "NoAutomationRecipe",
]
