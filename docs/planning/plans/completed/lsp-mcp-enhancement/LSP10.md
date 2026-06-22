---
id: LSP10
order: 10
plan: plan-lsp-mcp-enhancement-completed
state: done
wave: W3.1
phase: Phase 0
---

# Expand declared client capabilities

## Context

Wave W3.1 — Handshake correctness (prerequisites for later tool phases).

## Steps

In `lsp_lifecycle.py` `_client_capabilities()` (:266), declare:
- `codeAction`
- `completion` (+resolve)
- `signatureHelp`
- `formatting`/`rangeFormatting`
- `inlayHint`
- `callHierarchy`
- `typeDefinition`
- `implementation`

**Why:** Servers gate features on what the client advertises — pyright and typescript-language-server will return empty or refuse these unless declared here. Add the matching `textDocument.*` capabilities now so Phases 3/4/Completion do not silently under-deliver and look like bugs.

## Files

`lsp_lifecycle.py` (:266)

## Validation

Capability smoke test asserts each is present.

## Dependencies

None

## Notes

**Gates Phases 3/4/Completion — must land in Phase 0.**
