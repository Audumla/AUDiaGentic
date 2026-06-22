---
id: LSP21
order: 21
plan: plan-lsp-mcp-enhancement
state: not_done
wave: W7
phase: Phase 3-7
---

# Feature phases: navigation, code actions, provider routing, feedback loop

## Context

Wave W7 — Feature phases (independent, capability-gated).

## Steps

**W7.1 — Navigation (Phase 3):** `lsp_type_definition`, `lsp_implementation`, `lsp_call_hierarchy`, `lsp_symbol_context`. Depends: LSP10, LSP20.

**W7.2 — Code actions + format preview (Phase 4):** `lsp_code_actions`, `*_preview`, workspace-edit→patch (shared with rename), preview cache + TTL. Depends: LSP10, LSP13, LSP20.

**W7.3 — Provider routing policy (Phase 6):** routing config + defaults, update `sync_generic_lsp_mcp_to_providers`, `hybrid` mode, Codex default. Depends: LSP18.

**W7.4 — Agent feedback loop (Phase 7):** post-job changed-file diagnostics helper, bounded output. Depends: LSP18.

**W7.5 — Coding-quality split (Phase 5):** separate component plan; lint/format tools leave `coding-lsp`. Depends: none (planning), but ship after LSP18 contract is stable.

## Files

Multiple — see per-wave detail in plan

## Validation

Per-wave acceptance criteria in plan.

## Dependencies

LSP10, LSP20, LSP18

## Notes

Order by value; each depends on its Wave 3 capability + Wave 6 normalization.
