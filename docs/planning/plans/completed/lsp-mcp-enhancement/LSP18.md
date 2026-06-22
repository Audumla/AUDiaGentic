---
id: LSP18
order: 18
plan: plan-lsp-mcp-enhancement
state: done
wave: W5.4
phase: Phase 1
---

# file_diagnostics and changed_diagnostics service APIs and MCP tools

## Context

Wave W5.4 — Diagnostics v2 (Phase 1).

## Steps

Add `file_diagnostics` and `changed_diagnostics` service APIs + MCP tools + normalized schema.

**Normalized schema:** `{source, severity, code, message, file, range, related}`

Caller supplies changed-file list — `coding-lsp` does not own a source of truth for 'what changed'.

**Proposed tools:**
- `lsp_file_diagnostics(file, min_severity=4, timeout_ms=5000)`
- `lsp_changed_diagnostics(files, min_severity=4, limit=50)`
- `lsp_workspace_diagnostics(root='.', min_severity=4, limit=200)`
- `lsp_diagnostic_sources(root='.')`

## Files

`lsp_api.py`, `lsp_mcp.py`, `lsp_lifecycle.py`

## Validation

Pyright file diagnostics works after opening a Python file. TypeScript file diagnostics works. Editing a file on disk then calling file diagnostics returns results for the new content.

## Dependencies

LSP17

## Notes


