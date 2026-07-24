---
id: PRR07
order: 7
plan: plan-provider-recipe-refactor
state: completed
validate-first: true
priority: P1
work: M
---

# PRR07: Add regression tests for provider recipe model

## Description

Lock the architecture into docs and tests so future components do not put provider recipes into component packages or domain semantics into foundation toolchains.

## Steps

1. Create test_architecture_boundaries.py
2. Test foundation/toolchains doesn't import providers
3. Test ConfigPatcher has no MCP-specific helpers
4. Test memory component doesn't enumerate providers
5. Test hindsight.yaml has no enabled-providers
6. Test ProviderRecipeKind enum has expected values
7. Test ProviderRecipeResult.ok/fail create expected results
8. Test ProviderRecipeRegistry register/get/list_for_provider
9. Test hindsight matrix has rows and can be filtered by kind
10. Test LspRecipeAdapter maps descriptor fields correctly
11. Run all 14 tests to verify they pass

## Files

docs/standards/CREATING_A_COMPONENT.md
src/audiagentic/components/providers/adapters/README.md
src/audiagentic/foundation/toolchains/README.md
tests/unit/foundation/toolchains/
tests/unit/memory/
tests/unit/providers/

## Validation

1. All 14 tests pass
2. No foundation/toolchains imports from providers
3. No MCP-specific helpers in ConfigPatcher
4. Memory component boundary tests pass
5. Provider recipe model tests pass
6. Hindsight matrix tests pass
7. LSP adapter tests pass

## Effort & Risk

Risk is docs lagging implementation. Make docs part of acceptance, not cleanup.

## Notes

This closes the loop from the original failure: plan and docs must prevent the same architecture error.

