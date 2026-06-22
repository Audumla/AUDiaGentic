---
id: LSP12
order: 12
plan: unknown
state: draft
wave: W3.3
---

# Project-root marker resolution

## Wave 3 — Handshake correctness

Resolve to `Cargo.toml`/`tsconfig.json`/`compile_commands.json` dir, not cwd.

**Validate:** Nested file resolves to marker root.
**Files:** `lsp_api.py`
