---
id: PRR05
order: 5
plan: provider-recipe-refactor
state: completed
validate-first: true
priority: P1
work: L
---

# Superseded: keep Hindsight recipes in memory

## Description

SUPERSEDED BY HM03/HM05/HM07/PRR08 containment correction. This completed item
contains the old, rejected direction. Hindsight setup recipes must NOT be owned
by provider adapters or provider services. Hindsight-specific strategy data,
installer mapping, MCP/rule setup, and orchestration belong under
`src/audiagentic/components/memory/hindsight/`. Providers may expose only
generic descriptors, config writers, and recipe lifecycle seams.

## Steps

1. Define memory export contract: active backend id, base URL/API URL, token/auth metadata, transport, bank id/dynamic-bank options if supported, and mode (`external-api`, `existing-local`, `local-daemon`) if needed.
2. Remove provider refresh orchestration from `memory_api`. Memory config changes should emit or expose state; provider recipe orchestration should be called through provider management tooling.
3. Keep `HindsightMcpRecipe` under `components/memory/hindsight/`. It may call generic config primitives and provider descriptor lookup, but must not move into provider services.
4. Register Hindsight recipes from the memory implementation, not as provider-owned recipes. Representative coverage still matters: command installer, plugin/config, MCP+rule, wrapper/context-provider, and guidance/rules-only.
5. Keep generic surface contribution as fallback only, clearly labeled `rules-only` or `guidance-only`, and do not claim native installation.
6. Add provider APIs/MCP tools to install/uninstall/status Hindsight recipes explicitly, using dry-run where supported.

## Files

src/audiagentic/components/memory/memory_api.py
src/audiagentic/components/memory/hindsight_recipe.py
src/audiagentic/config/components/memory/hindsight.yaml
src/audiagentic/components/providers/adapters/*/
src/audiagentic/components/providers/services/recipes.py
src/audiagentic/components/providers/providers_api.py
src/audiagentic/components/providers/providers_mcp.py
tests/unit/memory/
tests/unit/providers/

## Validation

- `src/audiagentic/components/memory` contains no provider IDs, provider file paths, provider refresh calls, or MCP config helper code.
- Memory/hindsight status shows Hindsight state per provider/harness through contained recipes.
- At least four strategy kinds have tests using memory-owned Hindsight recipes plus generic provider seams.
- Official installer commands are represented as workflow steps or explicit action-needed guidance, not as ad hoc shell calls inside memory.

## Effort & Risk

Risk is attempting every provider at once. Stage implementation by strategy type, not by provider count.

## Notes

Historical note only. Do not execute the old provider-owned direction.
