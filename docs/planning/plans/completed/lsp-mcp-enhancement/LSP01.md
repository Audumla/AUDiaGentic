---
id: LSP01
order: 1
plan: plan-lsp-mcp-enhancement
state: done
wave: W0.1
phase: Phase 0
---

# Reader-loop notification dispatch

## Context

Wave W0.1 — Reader-loop message demux (unblocks everything).

## Steps

The reader loop currently only routes responses (`id in _pending`); notifications and server→client requests are dropped.

In `_reader_loop`, branch on message shape:
- `id` present + in `_pending` → response (current path)
- `method` present + no `id` → notification → invoke a registered callback map keyed by method
- neither → log + drop

Add `on_notification(method, handler)` registration.

## Files

`lsp_bridge.py`

## Validation

Fake server emits `textDocument/publishDiagnostics`; handler fires.

## Dependencies

None — first wave.

## Notes

Nothing downstream works until this is fixed. Gates Wave 5 (diagnostics).
