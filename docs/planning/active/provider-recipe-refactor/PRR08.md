---
id: PRR08
order: 8
plan: plan-provider-recipe-refactor
state: pending
validate-first: true
priority: P0
complexity: complex
---

# Completion gate — make provider recipes real and close boundary leaks

## Description

Finish the provider-recipe refactor to production quality. This item exists because PRR01-PRR07 were marked completed while key validation criteria remained false. Do not mark this completed until the existing scaffold is converted into working provider-owned recipe behavior, official Hindsight data is corrected, memory/toolchains boundaries are clean, and regression tests genuinely inspect the repo.

## Steps

1. Fix architecture regression tests first. Correct `WORKSPACE_ROOT` so tests inspect this repo, make missing target paths fail loudly, and invert the memory assertion so `COMPONENT_PROVIDERS` / provider surface imports are forbidden in `components/memory`.
2. Remove remaining memory-to-provider orchestration. Delete `_trigger_surface_reconcile` and provider imports from `memory_api.py`. Memory config changes may return `needs_provider_recipe_refresh: true` or expose backend export state, but must not call provider services.
3. Move or delete `components/memory/hindsight_recipe.py`. Any Hindsight MCP/config/hook/plugin recipe must live under `components/providers` or provider adapters. Memory may keep only a provider-agnostic export data class/function for active backend config.
4. Implement provider recipe lifecycle correctly. `ProviderRecipeRegistry.install()` must run full provision flow (`probe -> install -> configure -> verify` or recipe.provision). `uninstall()` must run full teardown (`prune -> uninstall -> cleanup -> verify absent` or recipe.teardown). Add tests that fail if only `install()` or only `prune()` is called.
5. Correct `hindsight_matrix.py` from official Hindsight docs. Replace placeholder `docs.hindsight.dev` URLs with official `https://hindsight.vectorize.io/sdks/integrations/...` URLs, record the actual checked date, and capture real install/uninstall/status commands. No placeholder dates like `2025-01-01`; no guessed commands.
6. Implement at least one real provider-owned Hindsight recipe for each representative strategy, using official docs: one command/hook installer (Codex or Cline), one plugin/config recipe (Claude or OpenCode), one MCP/rules CLI recipe (Copilot/Roo/OpenHands), and one guidance-only unsupported/no-source path. These recipes must not all wrap the same MCP config writer.
7. Add provider management API/MCP surface for recipes: list recipe status, dry-run install, install, uninstall/prune, and repair/reconfigure where supported. Declare tools in `providers.yaml` if exposed over MCP.
8. Remove provider allowlist/config concerns from `config/components/memory/hindsight.yaml`. Hindsight implementation options should describe backend connection only: base URL/API URL, auth, transport/mode, timeout, bank/dynamic-bank options if official docs require them.
9. Clean foundation/toolchains language and APIs. `foundation/toolchains` must contain only generic command/probe/config/artifact primitives. No MCP-specific helper APIs and no provider/component-specific examples in public docstrings/README.
10. Run focused tests and grep gates before marking complete: architecture boundaries, provider recipe lifecycle, Hindsight matrix, memory component, toolchain config patcher/artifact registry, and existing LSP recipe/native provider tests.

## Files

tests/unit/foundation/toolchains/test_architecture_boundaries.py
src/audiagentic/components/memory/memory_api.py
src/audiagentic/components/memory/hindsight_recipe.py
src/audiagentic/config/components/memory/hindsight.yaml
src/audiagentic/components/providers/services/recipes.py
src/audiagentic/components/providers/services/hindsight_matrix.py
src/audiagentic/components/providers/services/hindsight_recipes.py
src/audiagentic/components/providers/providers_api.py
src/audiagentic/components/providers/providers_mcp.py
src/audiagentic/config/components/providers.yaml
src/audiagentic/foundation/toolchains/
tests/unit/providers/
tests/unit/memory/
tests/unit/coding_lsp/

## Validation

- `python -m pytest tests/unit/foundation/toolchains/test_architecture_boundaries.py` fails on the current bad code before fixes and passes after fixes.
- `rg -n "COMPONENT_PROVIDERS|providers\.surfaces|apply_provider_surfaces|provider_id|claude|codex|copilot|opencode|cline|roo|openhands" src/audiagentic/components/memory` has no architecture violations. Mentions in README explaining the boundary are acceptable only if not executable guidance for memory-owned integration.
- `rg -n "MCP|mcp|provider|Hindsight|memory|coding-lsp|claude|codex" src/audiagentic/foundation/toolchains` has no public API/docstring violations. Internal generic tests may use arbitrary key names but must not reintroduce helper semantics.
- Provider recipe registry tests prove install invokes configure+verify and uninstall invokes prune+uninstall/teardown.
- Hindsight matrix rows have official `hindsight.vectorize.io` source URLs or explicit `no official source found`, with real checked dates.
- At least four representative Hindsight strategy tests exist and do not all use the same MCP-config implementation.
- Provider MCP/API tools for recipe management are discoverable if intended for operators.
- Existing LSP provider projection/native tests still pass.

## Effort & Risk

High risk because this touches architecture, tests, and provider behavior. Keep changes staged but do not mark complete for scaffolding or metadata-only mapping. The success condition is working lifecycle behavior plus passing boundary gates.

## Notes

This is a corrective completion gate for PRR01-PRR07. It should remain active until all failed validation from the review is resolved. Any code comment like `In production, this would...` inside recipe execution code is a blocker for completion.
