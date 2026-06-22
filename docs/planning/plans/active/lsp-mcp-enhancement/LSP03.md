---
id: LSP03
order: 3
plan: unknown
state: draft
wave: W1.1
---

# Collapse LspError/LspServerError into AudiaGenticError

## Wave 1 - Error model

Replace `LspError`/`LspServerError` subclasses with `AudiaGenticError(code=..., kind='coding-lsp', details=...)`. Preserve `EXT-LSP-001`/`002` payloads in `details`. Retarget call sites to catch `AudiaGenticError` + check `.code` before deleting the classes.

**Validate:** No subclass remains; Std 8 parallel-hierarchy grep clean.

**Files:** `lsp_bridge.py`, `lsp_session_manager.py`, `lsp_api.py`
