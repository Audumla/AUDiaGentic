---
id: LSP05
order: 5
plan: unknown
state: draft
wave: W2.1
---

# Per-request and method-specific timeouts

## Wave 2 — Request lifecycle & resilience

Replace the single 30s default with a method→timeout map and per-call override. Validate against performance-budget table.

**Depends:** LSP04
**Files:** `lsp_bridge.py`
