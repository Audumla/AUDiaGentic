---
id: PRR06
order: 6
plan: plan-provider-recipe-refactor
state: pending
validate-first: true
priority: P1
complexity: complex
---

# Align coding-lsp native support with provider recipe model

## Description

Use the existing LSP provider-native behavior as a second consumer of provider-owned recipes. Preserve current LSP behavior while reducing one-off fields where the generic provider recipe model can express the same lifecycle cleanly.

## Steps

1. Map current LSP fields to provider recipe concepts: `language_servers_config` = config recipe, `on_lsp_enabled` = native provision recipe, `receive_lsp_mcp` = generic MCP fallback policy.
2. Decide whether to keep these explicit fields as optimized provider descriptor shortcuts or wrap them in provider recipe adapters. Avoid a forced rewrite if compatibility cost is high.
3. If recipe adapters are added, make LSP use provider recipe orchestration for `provision_provider_lsp_support`, `sync_language_servers_to_provider_configs`, and `prune_language_servers_from_provider_configs` only where behavior remains identical.
4. Keep `coding_lsp` owning language server dependency selection and generic LSP backend config, but provider adapters owning native LSP config shapes.
5. Add tests proving current native language server sync and generic `ag-lsp` MCP projection still work.
6. Document shared model: capability component exports generic desired state; provider layer selects native recipe or generic fallback.

## Files

src/audiagentic/components/coding_lsp/language_servers_sync.py
src/audiagentic/components/coding_lsp/lsp_recipe.py
src/audiagentic/components/providers/services/lsp_projection.py
src/audiagentic/components/providers/descriptors/base.py
tests/unit/coding_lsp/test_lsp_recipe.py
tests/unit/providers/test_native_language_servers.py

## Validation

- Current LSP tests pass.
- Provider recipe model can describe LSP behavior in docs/code without losing `receive_lsp_mcp` fallback semantics.
- No provider-specific LSP config moves into `coding_lsp`.
- No LSP semantics move into foundation toolchains.

## Effort & Risk

Risk is destabilizing working LSP support. Treat LSP as alignment after Hindsight/provider recipe core is stable, not as first rewrite.

## Notes

LSP is proof that this pattern is broader than memory, but current behavior should not be churned unless recipe model clearly improves it.
