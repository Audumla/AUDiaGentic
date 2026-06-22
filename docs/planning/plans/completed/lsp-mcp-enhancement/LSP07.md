---
id: LSP07
order: 7
plan: plan-lsp-mcp-enhancement-completed
state: done
wave: W2.3
phase: Phase 0
---

# In-flight tracking and clean fail on server exit

## Context

Wave W2.3 — Request lifecycle & resilience.

## Steps

Already partially present (reader-loop except sets pending events); make it deterministic — on `_process` exit, fail all `_pending` with a crashed-server envelope.

## Files

`lsp_bridge.py`

## Validation

Kill server mid-request → caller gets envelope, not a hang.

## Dependencies

LSP04

## Notes


