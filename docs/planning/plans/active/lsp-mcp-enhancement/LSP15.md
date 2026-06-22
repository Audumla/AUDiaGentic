---
id: LSP15
order: 15
plan: unknown
state: draft
wave: W5.1
---

# Capture publishDiagnostics into per-uri cache

## Wave 5 — Diagnostics v2 (Phase 1)

Cache `textDocument/publishDiagnostics` by `(uri, version)` in `LspSession`.

**Depends:** LSP01
