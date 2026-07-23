"""Launch-env contribution seam (MO15).

Recipes and capabilities register DEFERRED env contributions per provider —
``{env-name: secret-ref-or-literal}`` — without resolving anything. Resolution
happens only inside :func:`launch_env_overlay`, the scoped context the
execution dispatch wraps around a provider launch, immediately before the
adapter spawns its subprocess. Resolved values exist transiently in
``os.environ`` for the duration of that launch frame (subprocesses inherit the
parent environment — there is no narrower channel) and are restored afterward;
they are never cached, persisted, logged, or surfaced in status/timelines.

Channel-priority note (RV338): providers run OUTSIDE AUDiaGentic in normal
operation. This seam is a SUPPLEMENT for AG-launched sessions only — a
provider whose only working key channel is this seam must report "works in
AG-launched sessions only", never plain enabled/auto. Ambient-environment
verification by the provider secret-reference service defines enablement.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from audiagentic.components.providers.services.secrets import (
    is_registered_scheme,
    parse_secret_ref,
    resolve_secret_ref,
)


def _looks_like_ref(value: str) -> bool:
    """A registered ``scheme:`` prefix marks a reference; anything else is a
    literal. A malformed ref with a REGISTERED scheme (e.g. ``env:bad name``)
    must fail loudly rather than be injected verbatim as a literal."""
    scheme, separator, _ = value.partition(":")
    return bool(separator) and is_registered_scheme(scheme)


# provider_id -> {env-name: secret-ref string ("env:NAME") or literal value}.
# Values here are REFERENCES or non-secret literals — never resolved secrets.
_contributions: dict[str, dict[str, str]] = {}


def register_launch_env_contribution(
    provider_id: str, env: dict[str, str], *, replace: bool = False
) -> None:
    """Register deferred env contributions for one provider.

    ``env`` maps env-var names to secret references (``env:NAME``) or literal
    non-secret values. Nothing is resolved at registration time.
    """
    current = {} if replace else dict(_contributions.get(provider_id, {}))
    current.update(env)
    _contributions[provider_id] = current


def remove_launch_env_contribution(provider_id: str, names: set[str] | None = None) -> None:
    """Remove some (or all, when *names* is None) contributions for a provider."""
    if names is None:
        _contributions.pop(provider_id, None)
        return
    current = _contributions.get(provider_id)
    if not current:
        return
    for name in names:
        current.pop(name, None)
    if not current:
        _contributions.pop(provider_id, None)


def list_launch_env_contributions(provider_id: str) -> dict[str, str]:
    """Report contribution env NAMES and ref SCHEMES only — never values.

    Literal (non-ref) contributions report as ``"literal"`` without content.
    This is the status/dry-run surface.
    """
    summary: dict[str, str] = {}
    for name, ref in _contributions.get(provider_id, {}).items():
        # Status listing must never raise; report the scheme prefix without
        # full parse-validation (validation happens at resolve time).
        summary[name] = ref.partition(":")[0] if _looks_like_ref(ref) else "literal"
    return summary


def _resolve_contributions(provider_id: str) -> dict[str, str]:
    """Resolve all of a provider's contributions at the launch boundary only."""
    resolved: dict[str, str] = {}
    for name, ref in _contributions.get(provider_id, {}).items():
        if _looks_like_ref(ref):
            # A malformed ref with a registered scheme raises VAL-CRED-001 here
            # instead of being injected verbatim.
            resolved[name] = resolve_secret_ref(parse_secret_ref(ref))
        else:
            resolved[name] = ref
    return resolved


@contextmanager
def launch_env_overlay(provider_id: str) -> Iterator[dict[str, str]]:
    """Scoped env injection around one provider launch.

    Resolves the provider's contributions, overlays them onto ``os.environ``
    (so the adapter's subprocess inherits them), and restores the previous
    environment on exit. Yields the env NAMES injected (values are not
    re-exposed through the yield).
    """
    resolved = _resolve_contributions(provider_id)
    previous: dict[str, str | None] = {}
    try:
        for name, value in resolved.items():
            previous[name] = os.environ.get(name)
            os.environ[name] = value
        yield {name: "injected" for name in resolved}
    finally:
        for name, old in previous.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


__all__ = [
    "launch_env_overlay",
    "list_launch_env_contributions",
    "register_launch_env_contribution",
    "remove_launch_env_contribution",
]
