---
id: LSP09
order: 9
plan: plan-lsp-mcp-enhancement-completed
state: done
wave: W2.5
phase: Phase 0
---

# Server restart/recovery and stale-session invalidation

## Context

Wave W2.5 — Request lifecycle & resilience.

## Steps

Detect dead/wedged session; allow `get_or_create` to rebuild; invalidate when config changes or command disappears.

## Files

`lsp_lifecycle.py`, `lsp_session_manager.py`

## Validation

Crashed server → new session created on next call.

## Dependencies

LSP07

## Notes


