---
id: LSP08
order: 8
plan: plan-lsp-mcp-enhancement
state: draft
wave: W2.4
phase: Phase 0
---

# stderr drain thread

## Context

Wave W2.4 — Request lifecycle & resilience.

## Steps

Spawn a daemon thread reading `stderr` to `logger.debug`. It is captured as a PIPE today but never read; a chatty server fills the OS pipe buffer, blocks on write, and presents as a hang.

## Files

`lsp_bridge.py`

## Validation

Chatty fake server does not wedge the request loop (fills-pipe regression test).

## Dependencies

None (independent; group here)

## Notes


