"""Provider-neutral session-surface resolution contract.

AS29 stage 3 (slice 3): typed input hint and neutral resolution outcome.
The resolver service lives in ``providers/services/session_surface_resolution``;
this module exposes only the request type and re-exports the foundation
resolved-surface snapshot so callers never import the resolver directly.

No ``components.agents`` imports — this contract is provider-layer only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

# Re-export the foundation snapshot type so callers can use this module as
# the single import point for the resolved surface shape.
from audiagentic.foundation.transports.session_surface import ResolvedSessionSurface

if TYPE_CHECKING:
    pass


@dataclass(frozen=True)
class SurfaceHint:
    """Typed request to resolve a session-surface snapshot.

    Carries only surface identity and optional version/platform hints.
    The ``provider_id`` is supplied explicitly by the resolver caller so that
    project-root provenance is always explicit on the resolution API boundary.
    No runtime config, adapter ref, or execution payload.
    """

    surface_id: str
    # Optional: narrows declaration selection to this version constraint.
    # Cannot substitute for installed-version discovery; only prunes candidates.
    version_hint: str | None = None
    # Optional: target platform string (e.g. "linux-amd64"). If absent the
    # resolver normalises to the current runtime platform via
    # ``runtime.system.platform.platform_key()``.
    platform_hint: str | None = None

    def __post_init__(self) -> None:
        value = self.surface_id
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "SurfaceHint.surface_id must be a non-empty string"
            )
        if self.version_hint is not None and (not isinstance(self.version_hint, str) or not self.version_hint.strip()):
            raise ValueError(
                "SurfaceHint.version_hint must be a non-empty string when set"
            )
        if self.platform_hint is not None and (not isinstance(self.platform_hint, str) or not self.platform_hint.strip()):
            raise ValueError(
                "SurfaceHint.platform_hint must be a non-empty string when set"
            )


__all__ = [
    "ResolvedSessionSurface",
    "SurfaceHint",
]
