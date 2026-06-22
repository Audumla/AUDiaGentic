---
id: LSP04
order: 4
plan: unknown
state: draft
wave: W1.2
---

# EXT-LSP-NNN code namespace and structured envelopes

## Wave 1 — Error model

Assign one code per envelope shape — timeout, unsupported-capability, crashed-server, invalid-position, file-not-found, no-configured-server. Build a single `_lsp_error(code, message, **details)` helper.

**Validate:** Each failure path returns its code; table documented.

**Depends:** LSP03
**Files:** `lsp_bridge.py`, `lsp_lifecycle.py`
