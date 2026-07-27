---
id: LSP16
order: 16
plan: lsp-mcp-enhancement
state: done
wave: W5.2
phase: Phase 1
---

# Mandatory disk→buffer re-sync before every file-scoped query

## Context

Wave W5.2 — Diagnostics v2 (Phase 1).

## Steps

Agents edit files on disk, but `sync_document` (`lsp_lifecycle.py:109`) holds an in-memory buffer and only re-sends on text mismatch. Every file diagnostic (and every position tool) must re-read current disk content, push it via `didChange` with a bumped version, and only then wait for the publish — otherwise the server answers from a stale buffer. Make this a single enforced path, not a per-caller convention.

## Files

`lsp_lifecycle.py` (:109), `lsp_api.py`

## Validation

Editing a file on disk then calling file diagnostics returns results for the new content, not the previously synced buffer.

## Dependencies

LSP11 (encoding), LSP12 (root)

## Notes

#1 source of wrong diagnostics.
