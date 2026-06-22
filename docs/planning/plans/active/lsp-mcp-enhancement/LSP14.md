---
id: LSP14
order: 14
plan: plan-lsp-mcp-enhancement
state: draft
wave: W4.2
phase: Phase 0
---

# Latency logging for all LSP requests

## Context

Wave W4.2 — Caching & observability (completes Phase 0).

## Steps

Wrap `send_request` with timing → `logger.debug` with method + ms.

## Files

`lsp_bridge.py`

## Validation

All requests logged with method name and duration.

## Dependencies

None

## Notes


