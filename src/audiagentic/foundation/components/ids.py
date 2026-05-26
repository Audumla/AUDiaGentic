"""Component ID constants — single source of truth for all component IDs.

Two groups:

  Core      — always present; scope determines project vs harness install root
  Optional  — installed per-project; each backed by a YAML component descriptor

Only YAML descriptors and this module may contain literal component ID strings.
All other Python code must import from here.
"""

from __future__ import annotations

# ── core ──────────────────────────────────────────────────────────────────────

COMPONENT_PROJECT = "project"
COMPONENT_SESSION = "session"           # harness-scoped; lives in audiagentic_home()

# ── optional ─────────────────────────────────────────────────────────────────

COMPONENT_AGENT_ACTIONS  = "agent-actions"
COMPONENT_AGENT_JOBS     = "agent-jobs"
COMPONENT_AGENT_LEDGER   = "agent-ledger"
COMPONENT_PLANNING       = "planning"
COMPONENT_PROVIDERS      = "providers"
COMPONENT_RELEASE        = "release"
COMPONENT_SOURCE_CONTROL = "source-control"
COMPONENT_CODING_LSP     = "coding-lsp"

# ── grouped sets ─────────────────────────────────────────────────────────────

CORE_COMPONENT_IDS: frozenset[str] = frozenset({
    COMPONENT_PROJECT,
    COMPONENT_SESSION,
})

OPTIONAL_COMPONENT_IDS: frozenset[str] = frozenset({
    COMPONENT_AGENT_ACTIONS,
    COMPONENT_AGENT_JOBS,
    COMPONENT_AGENT_LEDGER,
    COMPONENT_PLANNING,
    COMPONENT_PROVIDERS,
    COMPONENT_RELEASE,
    COMPONENT_SOURCE_CONTROL,
    COMPONENT_CODING_LSP,
})

ALL_COMPONENT_IDS: frozenset[str] = CORE_COMPONENT_IDS | OPTIONAL_COMPONENT_IDS
