---
id: LSP21
order: 21
plan: plan-lsp-mcp-enhancement
state: superseded
superseded-by: plan-lsp-capability-expansion (CAP01–07); caller fixes in CAP01 step 6; W7.5 deferred
validate-first: true
complexity: complex
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

## Architecture Standards Assessment

**Standards risk: Standard #6 (MCP Server Construction) and #8 (Error Handling).** All new tools must use `mcp_server(__name__)`. Result envelopes must follow the W6.3.4 convention. Provider routing (W7.3) must use config-driven policy, not hardcoded per-provider logic (Standard #2).

## Resolution Assessment

**Complexity: Complicated.** 5 phases with dependencies across waves.

**Solution:** W7.1: navigation tools (type definition, implementation, call hierarchy, symbol context). W7.2: code actions + format preview. W7.3: provider routing policy (config-driven). W7.4: agent feedback loop. W7.5: coding-quality split. Each phase is capability-gated and independent.

**Why complicated:** 5 phases, each with dependencies. LSP20 is a prerequisite. Significant new functionality. Provider routing must respect Standard #2 (config-driven).

## Dependencies

LSP10, LSP20, LSP18

## Notes

Order by value; each depends on its Wave 3 capability + Wave 6 normalization.