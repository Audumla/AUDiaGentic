"""System-installed harness resolution for the launcher.

Launch-time resolution selects a supported harness already installed on the
system; installation is an explicit provider-lifecycle operation, never an
implicit side effect of resolution. Harnesses are tried in
preference order (default: pi, then opencode, ...) and the first one whose CLI
is found on PATH wins.

This is the reuse-don't-duplicate contract: a "harness" here is just a CLI the
user currently has, resolved via ``shutil.which`` (the same mechanism the
providers layer uses via ``require_executable``).
"""
from __future__ import annotations

import shutil
from collections.abc import Sequence
from dataclasses import dataclass

# Harness type -> CLI executable name(s) to probe on PATH, in order. A harness
# whose CLI name differs from its type (or has fallbacks) is declared here;
# unknown types fall back to probing their own name.
_HARNESS_CLI_ALIASES: dict[str, tuple[str, ...]] = {
    "pi": ("pi",),
    "opencode": ("opencode",),
}

@dataclass(frozen=True)
class ResolvedHarness:
    """A supported harness found installed on the system."""

    harness_type: str
    cli_path: str


def _cli_aliases(harness_type: str) -> tuple[str, ...]:
    return _HARNESS_CLI_ALIASES.get(harness_type, (harness_type,))


def harness_cli_available(harness_type: str) -> str | None:
    """Return the resolved system CLI path for *harness_type*, or None.

    Probes the harness's CLI name(s) on PATH — never the embedded
    ``~/.audiagentic/harness`` copy.
    """
    for alias in _cli_aliases(harness_type):
        path = shutil.which(alias)
        if path:
            return path
    return None


def resolve_launch_harness(preference: Sequence[str]) -> ResolvedHarness | None:
    """Return the first system-installed harness in *preference* order.

    Args:
        preference: Harness types to try, most-preferred first. This is the
            caller's configured order (e.g. ``harness.order`` from the layered
            config) — never a hardcoded default; an empty sequence resolves to
            None.

    Returns:
        A :class:`ResolvedHarness` for the first installed harness, or None if
        none of the preferred harnesses is present on the system.
    """
    for harness_type in preference:
        cli_path = harness_cli_available(harness_type)
        if cli_path:
            return ResolvedHarness(harness_type=harness_type, cli_path=cli_path)
    return None


__all__ = [
    "ResolvedHarness",
    "harness_cli_available",
    "resolve_launch_harness",
]
