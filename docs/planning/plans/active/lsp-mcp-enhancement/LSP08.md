---
id: LSP08
order: 8
plan: unknown
state: draft
wave: W2.4
---

# Stderr drain thread

## Wave 2 — Request lifecycle & resilience

Spawn a daemon thread reading `stderr` to `logger.debug`. Prevents fills-pipe regression.

**Files:** `lsp_bridge.py`
