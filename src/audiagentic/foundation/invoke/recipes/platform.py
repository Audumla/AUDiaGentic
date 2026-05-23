from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..base import InvocationRecipe
from ..context import InvocationContext
from ..result import InvocationResult
from ..toolchains.detect import detect_pkg_manager, platform_key


@dataclass(frozen=True)
class PlatformRecipe(InvocationRecipe):
    """Select and execute a recipe variant based on the detected package manager.

    Resolution order:
    1. detect_fn() returns a PM name found in variants — use it.
    2. PM not in variants (or None) — check platform_fallback by platform_key().
    3. Neither — fail with a descriptive reason.
    """

    variants: dict[str, InvocationRecipe]
    platform_fallback: dict[str, InvocationRecipe] = field(default_factory=dict)
    detect_fn: Callable[[], str | None] = field(default=detect_pkg_manager)

    def _resolve(self) -> tuple[InvocationRecipe | None, str]:
        """Return (recipe, failure_reason). recipe is None only on failure."""
        pm = self.detect_fn()
        if pm and pm in self.variants:
            return self.variants[pm], ""
        pk = platform_key()
        if pk in self.platform_fallback:
            return self.platform_fallback[pk], ""
        if pm is None:
            reason = f"no supported package manager detected on platform '{pk}'"
        else:
            reason = f"no variant for package manager '{pm}' and no platform fallback for '{pk}'"
        return None, reason

    def plan(self, context: InvocationContext) -> InvocationResult:
        recipe, reason = self._resolve()
        if recipe is None:
            return InvocationResult(status="failed", reason=reason)
        return recipe.plan(context)

    def run(self, context: InvocationContext) -> InvocationResult:
        recipe, reason = self._resolve()
        if recipe is None:
            return InvocationResult(status="failed", reason=reason)
        return recipe.run(context)
