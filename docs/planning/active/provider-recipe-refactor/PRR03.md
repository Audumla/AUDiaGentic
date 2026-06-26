---
id: PRR03
order: 3
plan: plan-provider-recipe-refactor
state: pending
validate-first: true
priority: P0
complexity: mid
---

# Move MCP/config helpers out of foundation toolchains

## Description

Refactor current generic provisioning primitives so `foundation/toolchains` contains only generic command, probe, artifact, and structured-config operations. MCP-specific helpers and terminology move to provider services or adapter code.

## Steps

1. Replace `ConfigPatcher.add_mcp_entry` and `remove_mcp_entry` with generic `set_key` / `remove_key` usage at call sites, or move MCP convenience helpers into `components/providers/services/mcp.py`.
2. Update `recipe_contract.py` language so it describes installable host integrations generically without listing MCP/hooks/plugins as foundation-owned concepts.
3. Keep `ArtifactRegistry`, `ConfigKeyCheck`, `CommandProbe`, `FileExistsCheck`, and `StepRecipe` only if their APIs remain domain-neutral.
4. Review `artifact_registry` sidecar path. If it stays under `toolchain`, rename only if needed; otherwise document it as generic recipe artifact ownership without provider semantics.
5. Update exports in `foundation/toolchains/__init__.py` so no provider/MCP-specific helpers leak through.
6. Adjust tests to assert generic config mutation rather than MCP entry helpers.

## Files

src/audiagentic/foundation/toolchains/config_patcher.py
src/audiagentic/foundation/toolchains/recipe_contract.py
src/audiagentic/foundation/toolchains/__init__.py
src/audiagentic/components/providers/services/mcp.py
src/audiagentic/components/memory/hindsight_recipe.py or replacement location
tests/unit/foundation/toolchains/

## Validation

- `rg -n "MCP|mcp|provider|Hindsight|memory|coding-lsp" src/audiagentic/foundation/toolchains` returns only acceptable generic documentation references, ideally none for domain terms.
- Toolchain tests still prove command recipes, probes, config key mutation, and artifact pruning work.
- Provider MCP config behavior still passes provider tests after helper relocation.

## Effort & Risk

Risk is churn without benefit. Limit changes to domain leakage; do not rewrite generic workflow invocation unless required.

## Notes

This stage is the boundary repair the user called out: toolchains are generic manager primitives, not MCP/provider management.
