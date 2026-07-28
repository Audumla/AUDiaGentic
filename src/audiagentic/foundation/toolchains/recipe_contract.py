"""Provisioning recipe contract — generic lifecycle for installable integrations.

A :class:`ProvisioningRecipe` is the orchestration contract that higher-level
code implements to install, configure, verify, and remove an external host-side
integration.

Deliberately domain-neutral: this module names no concrete integrations,
components, or capability semantics. Concrete recipes compose the generic
primitives in this package into a capability-specific lifecycle.

Lifecycle state machine::

    absent --install--> installing --configure--> configuring --verify--> verified
       ^                                                                      |
       +----------------------------- uninstall/prune ------------------------+

Any step may transition to ``error``.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, TypeVar


class RecipeState(str, Enum):
    """Lifecycle position of an integration managed by a recipe."""

    ABSENT = "absent"
    INSTALLING = "installing"
    CONFIGURING = "configuring"
    VERIFIED = "verified"
    UPGRADE_AVAILABLE = "upgrade-available"
    UPGRADING = "upgrading"
    UPGRADED = "upgraded"
    NOT_APPLICABLE = "not-applicable"
    ERROR = "error"


@dataclass
class RecipeResult:
    """Structured outcome of a single recipe lifecycle operation.

    ``artifacts_owned`` lists the stable identifiers (file paths, ``file::key``
    paths, hook ids) the operation created or now manages, so callers can hand
    them to an :class:`~.artifact_registry.ArtifactRegistry` for later prune.

    ``action_needed`` carries user-facing guidance when automation cannot fully
    proceed (an unverified source, a manual install step, a required restart) —
    a generic "a human must do X" signal, not tied to any one integration.
    """

    success: bool
    state: RecipeState
    artifacts_owned: list[str] = field(default_factory=list)
    status: str = ""
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    action_needed: str = ""

    @classmethod
    def ok(
        cls,
        state: RecipeState,
        *,
        artifacts: list[str] | None = None,
        status: str = "",
        details: dict[str, Any] | None = None,
        action_needed: str = "",
    ) -> RecipeResult:
        return cls(
            success=True,
            state=state,
            artifacts_owned=list(artifacts or []),
            status=status,
            details=dict(details or {}),
            action_needed=action_needed,
        )

    @classmethod
    def fail(
        cls,
        error: str,
        *,
        state: RecipeState = RecipeState.ERROR,
        details: dict[str, Any] | None = None,
        action_needed: str = "",
    ) -> RecipeResult:
        return cls(
            success=False,
            state=state,
            error=error,
            details=dict(details or {}),
            action_needed=action_needed,
        )


# A cleanup hook performs integration-specific teardown that falls outside generic
# file/key/hook management — e.g. calling a backend API to deregister a client.
# It receives the recipe context and raises on failure.
CleanupHook = Callable[[dict[str, Any]], None]


_ResultT = TypeVar("_ResultT", bound="RecipeResult")


def run_steps(
    steps: Sequence[Any],
    context: dict[str, Any],
    *,
    ok_state: RecipeState = RecipeState.INSTALLING,
    ok_status: str = "steps succeeded",
    fail_prefix: str = "step sequence failed",
) -> RecipeResult:
    """Run managed steps through canonical SequenceStep, returning a RecipeResult.

    Shared adapter between the step layer's SequenceResult and the recipe
    layer's RecipeResult so lifecycle methods don't each re-implement the
    run/branch/format dance.
    """
    from audiagentic.foundation.steps import SequenceStep

    seq_result = SequenceStep(list(steps), id="recipe-sequence", compensate_on_failure=True).run(context)
    if seq_result.status == "ok":
        return RecipeResult.ok(ok_state, status=ok_status)
    return RecipeResult.fail(
        f"{fail_prefix}: {seq_result.reason or 'unknown'}",
        details={"steps": seq_result.outputs.get("steps", [])},
    )


class ProvisioningRecipe(ABC):
    """Abstract lifecycle contract for an installable integration.

    Subclasses implement the six lifecycle primitives. :meth:`provision` and
    :meth:`teardown` provide a default orchestration that most recipes can reuse
    unchanged; override them only when the default ordering does not fit.

    The return type of lifecycle methods is covariant: subclasses may narrow
    ``RecipeResult`` to a richer typed result for their family contract.
    """

    #: Provider-specific teardown callables run during :meth:`teardown`, after
    #: generic prune. Populate in ``__init__`` of a concrete recipe (RV01).
    custom_cleanup_hooks: list[CleanupHook]

    #: When False, :meth:`provision` ignores ``provision_steps()`` and always
    #: uses the primitive-call path. Set on recipes whose ``provision_steps()``
    #: exists for introspection/dry-run only and does not fully represent
    #: provisioning (e.g. configure() performs work the steps cannot express).
    provision_via_steps: bool = True

    def __init__(self) -> None:
        self.custom_cleanup_hooks = []

    # --- lifecycle primitives ------------------------------------------------

    @abstractmethod
    def probe(self, context: dict[str, Any]) -> RecipeResult:
        """Report current state without mutating anything.

        Return a result whose ``state`` is :attr:`RecipeState.VERIFIED` when the
        integration is already fully installed and configured (enabling an
        idempotent skip), :attr:`RecipeState.ABSENT` otherwise.
        """

    @abstractmethod
    def install(self, context: dict[str, Any]) -> RecipeResult:
        """Acquire the integration (run installer, drop package, fetch binary)."""

    @abstractmethod
    def configure(self, context: dict[str, Any]) -> RecipeResult:
        """Apply managed configuration (config keys, hook wiring, server entries)."""

    @abstractmethod
    def verify(self, context: dict[str, Any]) -> RecipeResult:
        """Confirm install + configure succeeded, using probe primitives."""

    @abstractmethod
    def uninstall(self, context: dict[str, Any]) -> RecipeResult:
        """Reverse :meth:`install` (remove binary/package/plugin)."""

    @abstractmethod
    def prune(self, context: dict[str, Any]) -> RecipeResult:
        """Remove managed configuration/artifacts, leaving user content intact."""

    def upgrade(self, context: dict[str, Any]) -> RecipeResult:
        """Reconcile an owned present dependency to its declared target.

        Upgrade is deliberately explicit: recipes must never perform it as part
        of a normal probe, status query, or launch path.  The conservative
        default keeps existing configuration-only and externally-owned recipes
        compatible while making their non-applicability visible to callers.
        Recipes that own versioned artifacts override this method and return
        ``UPGRADED`` or ``VERIFIED`` (already current), with provenance in
        ``details``.
        """
        return RecipeResult.ok(
            RecipeState.NOT_APPLICABLE,
            status="upgrade is not applicable to this recipe",
        )

    def dry_run(self, context: dict[str, Any]) -> RecipeResult:
        """Describe what :meth:`provision` would do, without doing any of it.

        Concrete, non-abstract: a recipe that cannot describe its plan reports
        that honestly rather than forcing every implementer to write a stub.
        Overrides MUST NOT execute commands or write files — this backs the
        public ``plan`` mode, and a query that mutates is a defect (RV497).
        """
        return RecipeResult.ok(RecipeState.ABSENT, status="no plan available")

    # --- result conversion ----------------------------------------------------

    def to_result(self, base: RecipeResult) -> RecipeResult:
        """Convert an orchestration result to this recipe's result type.

        Every result returned by :meth:`provision`, :meth:`teardown`, and
        :meth:`post_uninstall_verify` is routed through this hook, so
        subclasses that narrow ``RecipeResult`` (or overlay metadata such as
        provenance) override this single method instead of re-implementing
        the orchestration. Default: identity.
        """
        return base

    # --- default orchestration ----------------------------------------------

    def provision(self, context: dict[str, Any]) -> RecipeResult:
        """Run probe -> install -> configure -> verify with idempotent skip.

        If :meth:`probe` reports the integration already verified, returns early
        without re-installing. Stops and returns the failing result on any error.

        When the recipe exposes ``provision_steps()`` (TO12), execution delegates
        to :class:`audiagentic.foundation.steps.SequenceStep` for structured rollback
        instead of the primitive-call path. Recipes whose ``configure`` does work
        the steps cannot express must return an empty step list to stay on the
        primitive path.

        Results are never mutated in place (subclasses may return frozen
        dataclasses); adjustments use :func:`dataclasses.replace`.
        """
        probed = self.probe(context)
        if probed.success and probed.state is RecipeState.VERIFIED:
            return self.to_result(RecipeResult.ok(
                RecipeState.VERIFIED,
                status="already provisioned",
                details=probed.details,
            ))

        # TO12: structured step path with rollback
        provision_steps_fn = (
            getattr(self, "provision_steps", None) if self.provision_via_steps else None
        )
        steps = provision_steps_fn() if callable(provision_steps_fn) else None  # type: ignore[operator]
        if steps:
            seq = run_steps(steps, context, fail_prefix="provision sequence failed")
            if not seq.success:
                return self.to_result(seq)
            verified = self.verify(context)
            if not verified.success:
                verified = replace(verified, state=RecipeState.ERROR)
            return self.to_result(verified)

        # Legacy primitive-call path
        owned: list[str] = []
        for op in (self.install, self.configure):
            result = op(context)
            owned.extend(result.artifacts_owned)
            if not result.success:
                return self.to_result(replace(result, artifacts_owned=owned))

        verified = self.verify(context)
        verified = replace(
            verified, artifacts_owned=[*owned, *verified.artifacts_owned]
        )
        if not verified.success:
            # verify failure is terminal: surface the diagnostic, do not proceed.
            verified = replace(verified, state=RecipeState.ERROR)
        return self.to_result(verified)

    def teardown(self, context: dict[str, Any]) -> RecipeResult:
        """Run prune -> uninstall -> cleanup hooks -> post-uninstall verify."""
        pruned = self.prune(context)
        if not pruned.success:
            return self.to_result(pruned)

        removed = self.uninstall(context)
        if not removed.success:
            return self.to_result(removed)

        try:
            self.run_cleanup_hooks(context)
        except Exception as exc:  # noqa: BLE001 - report hook failure, do not crash
            return self.to_result(RecipeResult.fail(f"cleanup hook failed: {exc}"))

        return self.post_uninstall_verify(context)

    def post_uninstall_verify(self, context: dict[str, Any]) -> RecipeResult:
        """Confirm teardown left no managed artifacts. Default: re-probe absent.

        Override for stricter orphan detection. The default treats a probe that
        reports :attr:`RecipeState.ABSENT` as success.
        """
        probed = self.probe(context)
        if probed.success and probed.state is RecipeState.ABSENT:
            return self.to_result(RecipeResult.ok(RecipeState.ABSENT, status="removed"))
        return self.to_result(RecipeResult.fail(
            "integration still present after teardown",
            details=probed.details,
        ))

    def run_cleanup_hooks(self, context: dict[str, Any]) -> None:
        """Invoke each registered cleanup hook in order. Raises on first failure."""
        for hook in self.custom_cleanup_hooks:
            hook(context)


__all__ = [
    "CleanupHook",
    "ProvisioningRecipe",
    "RecipeResult",
    "RecipeState",
    "run_steps",
]
