---
id: LSP17
order: 17
plan: plan-lsp-mcp-enhancement
state: done
wave: W5.3
phase: Phase 1
---

# Version-correlated publish wait

## Context

Wave W5.3 — Diagnostics v2 (Phase 1).

## Steps

Servers emit publishes asynchronously and may send a stale-version publish after a new `didChange`, or multiple publishes per version. Wait for a publish whose version is `>=` the version just sent (with a short settle window). The pyright 'omits version' fallback must still gate on the last `did_change` stamp, not blindly accept the next arrival.

## Files

`lsp_bridge.py`, `lsp_session_manager.py`

## Validation

Stale-version publishes are rejected; correct version accepted.

## Dependencies

LSP15, LSP16

## Notes


