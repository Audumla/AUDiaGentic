---
id: LSP06
order: 6
plan: plan-lsp-mcp-enhancement
state: draft
wave: W2.2
phase: Phase 0
---

# Send $/cancelRequest on timeout

## Context

Wave W2.2 — Request lifecycle & resilience.

## Steps

On `event.wait` expiry, send `$/cancelRequest` with the request id before raising the timeout envelope. This stops the server from computing abandoned work during edit loops.

## Files

`lsp_bridge.py`

## Validation

Hung request cancels; later requests still succeed.

## Dependencies

LSP05

## Notes


