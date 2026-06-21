"""Component ID constants.

Core IDs are the canonical source (no YAML descriptor exists for them).

Optional component IDs below are **deprecated** — they duplicate the IDs
already defined in each component's YAML descriptor.  New code should look
up IDs from the descriptor registry via :func:`get_optional_component_ids`.
Existing callers may continue importing the individual constants during
transition; they will be removed once all callers migrate.

Only YAML descriptors and this module may contain literal component ID
strings.  All other Python code must import from here (or use the
descriptor registry).
"""

from __future__ import annotations

# ── core (always present; no YAML descriptor) ────────────────────────────────

COMPONENT_PROJECT = "project"
COMPONENT_SESSION = "session"  # harness-scoped; lives in audiagentic_home()

# ── optional (deprecated — duplicates YAML descriptors) ──────────────────────
# Migrate callers to get_optional_component_ids() or descriptor lookup.

COMPONENT_AGENT_JOBS     = "agent-jobs"
COMPONENT_AGENT_LEDGER   = "agent-ledger"
COMPONENT_PROVIDERS      = "providers"
COMPONENT_RELEASE        = "release"
COMPONENT_SOURCE_CONTROL = "source-control"
COMPONENT_CODING_LSP     = "coding-lsp"


def get_optional_component_ids() -> frozenset[str]:
    """Return optional component IDs derived from loaded descriptors.

    Prefer this over the individual ``COMPONENT_*`` constants for optional
    components.  Returns an empty frozenset if the descriptor registry has
    not yet been populated (early bootstrap).
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


# ── grouped sets ─────────────────────────────────────────────────────────────

CORE_COMPONENT_IDS: frozenset[str] = frozenset({
    COMPONENT_PROJECT,
    COMPONENT_SESSION,
})

OPTIONAL_COMPONENT_IDS: frozenset[str] = frozenset({
    COMPONENT_AGENT_JOBS,
    COMPONENT_AGENT_LEDGER,
    COMPONENT_PROVIDERS,
    COMPONENT_RELEASE,
    COMPONENT_SOURCE_CONTROL,
    COMPONENT_CODING_LSP,
})

ALL_COMPONENT_IDS: frozenset[str] = CORE_COMPONENT_IDS | OPTIONAL_COMPONENT_IDS
