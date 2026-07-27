---
id: LSP15
order: 15
plan: lsp-mcp-enhancement
state: done
wave: W5.1
phase: Phase 1
---

# Capture publishDiagnostics into per-uri cache

## Context

Wave W5.1 — Diagnostics v2 (Phase 1).

## Steps

Capture `textDocument/publishDiagnostics` (uses Phase 0 notification dispatch). Cache by `(uri, version)` in `LspSession`. Many servers (pyright) omit `version` in publish; fall back to stamping the cache with the last `did_change` version and accept the next publish for that uri as current.

## Files

`lsp_bridge.py`, `lsp_session_manager.py`

## Validation

Publish events are cached and retrievable by uri.

## Dependencies

LSP01

## Notes


