---
id: PRR05
order: 5
plan: plan-provider-recipe-refactor
state: pending
validate-first: true
priority: P1
complexity: complex
---

# Migrate Hindsight integration to provider-owned recipes

## Description

Refactor Hindsight support so the memory component only exports active backend config, while provider adapters own Hindsight setup recipes for their harness. Replace generic prompt-only behavior as the primary integration path where official recipes exist.

## Steps

1. Define memory export contract: active backend id, base URL/API URL, token/auth metadata, transport, bank id/dynamic-bank options if supported, and mode (`external-api`, `existing-local`, `local-daemon`) if needed.
2. Remove provider refresh orchestration from `memory_api`. Memory config changes should emit or expose state; provider recipe orchestration should be called through provider management tooling.
3. Move `HindsightMcpRecipe` out of `components/memory` if it remains useful. Preferred owner is providers recipe services or provider adapter modules, because MCP config shape is provider/harness behavior.
4. Register provider-owned Hindsight recipes per PRR04 matrix. Start with representative coverage: one command installer (`codex` or `cline`), one plugin config (`opencode` or `claude`), one MCP+rule CLI (`copilot`/`roo`/`openhands`), and one wrapper/context-provider (`aider` or `continue_`).
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
- Provider recipe status shows Hindsight state per provider/harness.
- At least four strategy kinds have tests using provider-owned recipes.
- Official installer commands are represented as workflow steps or explicit action-needed guidance, not as ad hoc shell calls inside memory.

## Effort & Risk

Risk is attempting every provider at once. Stage implementation by strategy type, not by provider count.

## Notes

This is where current prompt-only integration becomes real harness setup. Memory remains generic; providers perform recipes.
