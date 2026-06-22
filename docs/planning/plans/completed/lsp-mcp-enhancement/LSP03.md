---
id: LSP03
order: 3
plan: plan-lsp-mcp-enhancement
state: done
wave: W1.1
phase: Phase 0
---

# Collapse LspError/LspServerError into AudiaGenticError

## Context

Wave W1.1 — Error model (one canonical type before errors multiply).

## Steps

Replace both subclasses with `AudiaGenticError(code=..., kind='coding-lsp', details=...)` (or a thin `make_error()` factory).

**Line anchors:** `lsp_bridge.py:22,37` defines `class LspError(AudiaGenticError)` and `class LspServerError(AudiaGenticError)`.

Preserve `EXT-LSP-001` (server error code) / `EXT-LSP-002` (process death) payloads as `details`.

Audit ~6 `except LspError`/`except LspServerError` call sites: bridge `shutdown`, session manager, `lsp_api`. Retarget to `AudiaGenticError` + code checks **before** deleting the classes.

**Std 8 rationale:** `ARCHITECTURE_STANDARDS.md` §8 forbids this verbatim: *'No parallel hierarchies (`EventBusError`, `LspError`).'*

## Files

`lsp_bridge.py` (defs at :22,:37), `lsp_session_manager.py`, `lsp_api.py`

## Validation

No subclass remains; Std 8 parallel-hierarchy grep clean; existing catch sites still function.

## Dependencies

None (can run parallel to Wave 0, but must precede Wave 2+)

## Notes

Do this before every later item starts raising errors, or the cleanup compounds.
