---
id: LSP12
order: 12
plan: plan-lsp-mcp-enhancement
state: done
wave: W3.3
phase: Phase 0
---

# Project-root marker resolution

## Context

Wave W3.3 — Handshake correctness (prerequisites for later tool phases).

## Steps

Sessions are keyed on the passed root/cwd, but `rust-analyzer`/`typescript-language-server`/`clangd` need the project-marker directory:
- Rust: `Cargo.toml`
- TypeScript: `tsconfig.json`/`package.json`
- C/C++: `compile_commands.json`

Resolve to marker dir, not cwd. A wrong root yields empty or misconfigured results that look like missing capability.

## Files

`lsp_api.py` `resolve_project_root`/`_open_file_session`, per-language markers

## Validation

Nested file resolves to marker root.

## Dependencies

None

## Notes


