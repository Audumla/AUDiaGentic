"""Core component ID constants.

Core components have no YAML descriptor, so this module is their canonical
source. Every other component's ID lives in its YAML descriptor
(config/components/*.yaml); Python code obtains those IDs either from the
descriptor registry (:func:`get_optional_component_ids` / ``all_descriptors``)
or — inside the owning component's own package only — from a module-level
``_COMPONENT_ID`` self-ID constant. Cross-component references outside those
places should be rare and carry a justifying comment.
"""

from __future__ import annotations

# ── core (always present; no YAML descriptor) ────────────────────────────────

COMPONENT_PROJECT = "project"
COMPONENT_SESSION = "session"  # harness-scoped; lives in audiagentic_home()

CORE_COMPONENT_IDS: frozenset[str] = frozenset({
    COMPONENT_PROJECT,
    COMPONENT_SESSION,
})


def get_optional_component_ids() -> frozenset[str]:
    """Return optional component IDs derived from loaded descriptors.

    Returns an empty frozenset if the descriptor registry has not yet been
    populated (early bootstrap).
    """
    try:
        from audiagentic.foundation.components.registry import all_descriptors

        return frozenset(
            cid
            for cid, desc in all_descriptors().items()
            if not desc.core
        )
    except ImportError:
        return frozenset()
