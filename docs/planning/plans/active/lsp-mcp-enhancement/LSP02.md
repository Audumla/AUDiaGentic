---
id: LSP02
order: 2
plan: plan-lsp-mcp-enhancement
state: draft
wave: W0.2
phase: Phase 0
---

# Server→client request handling

## Context

Wave W0.2 — Reader-loop message demux (unblocks everything).

## Steps

`method` present + `id` present → inbound request. Reply to:
- `workspace/configuration` (null/defaults per item)
- `client/registerCapability` (ack/empty result)

Default-reply null + log for unknown server requests. Write a JSON-RPC response with the same `id`.

**Why:** Pyright and typescript-language-server block on `workspace/configuration`; without a reply they stall and never publish diagnostics. This is a prerequisite for Phase 1, not optional.

## Files

`lsp_bridge.py`

## Validation

Fake server issues `workspace/configuration`; bridge replies; server unblocks and proceeds to publish.

## Dependencies

LSP01 (shared demux branch)

## Notes

This is the pyright/tsserver stall fix.
