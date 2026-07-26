"""Foundation capabilities — domain-neutral registration for cross-boundary access.

RU02: product components may not import runtime orchestration packages directly.
Capabilities provide a registered seam so product code depends on foundation
interfaces rather than runtime implementation modules.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_HARNESS_STATUS: dict[str, Callable[..., Any]] | None = None


def register_harness_status(functions: dict[str, Callable[..., Any]]) -> None:
    """Register the concrete harness-status implementation at composition root.

    Must be called once during process bootstrap (composition root). Raises if
    already registered or not registered yet depending on state.
    """
    global _HARNESS_STATUS
    if _HARNESS_STATUS is not None:
        return  # idempotent re-registration
    _HARNESS_STATUS = dict(functions)


def get_harness_status() -> dict[str, Callable[..., Any]]:
    """Resolve the registered harness-status implementation.

    Raises RuntimeError if called before composition-root wiring completes
    (should only happen in tests or misconfigured bootstrapping).
    """
    if _HARNESS_STATUS is None:
        raise RuntimeError(
            "harness_status capability not wired — register_harness_status() "
            "must be called at composition root before product components resolve it"
        )
    return _HARNESS_STATUS


def reset_harness_status() -> None:
    """Reset the registered capability. Used for test isolation."""
    global _HARNESS_STATUS
    _HARNESS_STATUS = None
