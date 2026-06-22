---
id: LSP10
order: 10
plan: unknown
state: draft
wave: W3.1
---

# Expand declared client capabilities

## Wave 3 — Handshake correctness

Declare `codeAction`, `completion`(+resolve), `signatureHelp`, `formatting`/`rangeFormatting`, `inlayHint`, `callHierarchy`, `typeDefinition`, `implementation` in `_client_capabilities()`.

**Validate:** Capability smoke test asserts each is present.

**Gates:** Phases 3/4/Completion — must land in Phase 0.
**Files:** `lsp_lifecycle.py`
