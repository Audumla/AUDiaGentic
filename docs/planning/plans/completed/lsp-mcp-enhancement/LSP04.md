---
id: LSP04
order: 4
plan: plan-lsp-mcp-enhancement-completed
state: done
wave: W1.2
phase: Phase 0
---

# EXT-LSP-NNN code namespace and structured envelopes

## Context

Wave W1.2 — Error model (one canonical type before errors multiply).

## Steps

Reserve the `EXT-LSP-NNN` range (already in use: `001` server error, `002` process death). Assign one code per envelope shape:
- Timeout
- Unsupported-capability
- Crashed-server
- Invalid-position
- File-not-found
- No-configured-server

Build a single `_lsp_error(code, message, **details)` helper all sites use. Document the table beside the bridge so later phases reuse codes instead of inventing strings.

## Files

`lsp_bridge.py`, `lsp_lifecycle.py`

## Validation

Each failure path returns its code; table documented beside the bridge.

## Dependencies

LSP03

## Notes


