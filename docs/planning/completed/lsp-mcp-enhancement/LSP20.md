---
id: LSP20
order: 20
plan: plan-lsp-mcp-enhancement
state: superseded
superseded-by: plan-lsp-capability-expansion
validate-first: true
work: L
wave: W6
phase: Phase 2
---

# Capability discovery, normalization, and tool ergonomics

## Context

Wave W6 — Capability discovery + tool ergonomics (Phase 2).

## Steps

**W6.1 — `lsp_capabilities(file_or_language)`** exposing stored initialize caps; add capability checks to all tools.

**W6.2 — Normalize** symbols, locations, hovers, workspace edits to shared schema.

**W6.3 — Tool ergonomics** (the agent-usability gate):
1. **Docstrings on every MCP tool.** `lsp_mcp.py`/`lsp_manage_mcp.py` tools have no docstrings; FastMCP surfaces the docstring as the tool description.
2. **Self-documenting `position`.** `position: str` is parsed as `'line:col'`, **1-based** (`parse_position`, `lsp_api.py:45`). Either document the format and base in the description, or change the signature to explicit `line: int, character: int` with the base stated.
3. **Document `min_severity` semantics.** `1=Error … 4=Hint` is explained only on an internal method; surface it in the tool description.
4. **One consistent result/error envelope.** Today success and the `{"error": ...}` path (`_open_file_session`, `lsp_api.py:145`) return different shapes; align them.
5. **Symbol→position workflow note** in the `lsp_symbols`/navigation descriptions.

## Files

`lsp_api.py`, `lsp_mcp.py`, `lsp_manage_mcp.py`

## Validation

Agent can ask what LSP can do for current file. Every MCP tool has a description and documented parameters. Position round-trip has no off-by-one. Success and error results share a documented envelope shape across all tools.

## Architecture Standards Assessment

**Standards risk: Standard #6 (MCP Server Construction) and #8 (Error Handling).** All tools must use `mcp_server(__name__)` — existing tools comply. Result envelopes must be consistent (W6.3.4 addresses this directly). Error handling must use `AudiaGenticError` with canonical codes.

## Resolution Assessment

**Complexity: Moderate.** Many touch points, but each sub-task is self-contained.

**Solution:** W6.1: add `lsp_capabilities(file_or_language)` MCP tool. W6.2: normalize symbols/locations/hovers to shared schema. W6.3: docstrings on every MCP tool, self-documenting position format, document min_severity semantics, one consistent result/error envelope, symbol→position workflow note.

**Why moderate:** 3 files but many touch points across all MCP tools. Each sub-task is independent and can be validated separately.

## Dependencies

LSP10, LSP18

## Notes

This is the deterministic, provider-neutral fix that must land before any skill layer is considered.