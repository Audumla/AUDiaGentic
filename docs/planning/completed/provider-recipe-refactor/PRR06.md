---
id: PRR06
order: 6
plan: plan-provider-recipe-refactor
state: completed
validate-first: true
priority: P1
work: L
---

# PRR06: Align coding-lsp with provider recipe model

## Description

Use the existing LSP provider-native behavior as a second consumer of provider-owned recipes. Preserve current LSP behavior while reducing one-off fields where the generic provider recipe model can express the same lifecycle cleanly.

## Steps

1. Create lsp_recipes.py adapter module in providers/services/
2. Define LspRecipeAdapter dataclass with from_descriptor factory
3. Implement map_lsp_fields_to_recipe_concepts() function
4. Map language_servers_config → config recipe
5. Map on_lsp_enabled → native provision recipe
6. Map receive_lsp_mcp → generic MCP fallback policy
7. Run tests to verify no behavior changes

## Files

src/audiagentic/components/coding_lsp/language_servers_sync.py
src/audiagentic/components/coding_lsp/lsp_recipe.py
src/audiagentic/components/providers/services/lsp_projection.py
src/audiagentic/components/providers/descriptors/base.py
tests/unit/coding_lsp/test_lsp_recipe.py
tests/unit/providers/test_native_language_servers.py

## Validation

1. LspRecipeAdapter.from_descriptor maps all fields correctly
2. map_lsp_fields_to_recipe_concepts returns expected mapping
3. No behavioral changes to existing LSP provisioning
4. All 14 regression tests pass

## Effort & Risk

Risk is destabilizing working LSP support. Treat LSP as alignment after Hindsight/provider recipe core is stable, not as first rewrite.

## Notes

LSP is proof that this pattern is broader than memory, but current behavior should not be churned unless recipe model clearly improves it.
