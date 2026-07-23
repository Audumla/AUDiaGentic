"""Semantic IDs used by core lifecycle and core component entry points.

Configuration remains authoritative in ``config/components/project.yaml`` and
``session.yaml``. These constants exist only where Python behavior must identify
one of those components semantically; a conformance test keeps them aligned
with the core descriptors. Registry enumeration belongs to ``registry.py``.
"""

from __future__ import annotations

# ── core (always present; no YAML descriptor) ────────────────────────────────

COMPONENT_PROJECT = "project"
COMPONENT_SESSION = "session"  # harness-scoped; lives in audiagentic_home()

CORE_COMPONENT_IDS: frozenset[str] = frozenset({
    COMPONENT_PROJECT,
    COMPONENT_SESSION,
})
