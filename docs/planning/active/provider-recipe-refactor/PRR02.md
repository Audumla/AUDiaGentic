---
id: PRR02
order: 2
plan: plan-provider-recipe-refactor
state: pending
validate-first: true
priority: P0
complexity: complex
---

# Define provider-owned capability recipe contract

## Description

Create a provider-owned recipe model for installing, configuring, verifying, and removing capability integrations. Recipes are scoped to provider + capability + backend, compose generic workflow/toolchain primitives, and own provider-specific files, commands, hooks, plugins, and MCP config semantics.

## Steps

1. Add provider-layer types under `components/providers`, not foundation toolchains. Candidate: `ProviderCapabilityRecipe`, `ProviderRecipeResult`, `ProviderRecipeKind`, and registry keyed by `(provider_id, capability_id, backend_id)`.
2. Recipe lifecycle should cover `probe/status`, `install`, `configure`, `verify`, `uninstall`, and `prune`. Use foundation `ShellStep`, `SequenceStep`, `CallableStep`, probes, and generic config patch helpers as implementation primitives.
3. Support common strategy kinds discovered from Hindsight and LSP: `command-installer`, `mcp-config`, `hooks`, `plugin-config`, `rules`, `wrapper-cli`, `context-provider`, `native-pass-through`, and `hybrid`.
4. Keep provider recipes responsible for config path resolution, provider-specific schema translation, installer command composition, and user-facing action-needed messages.
5. Add provider management API surface for recipes: list applicable recipes, recipe status, install recipe, uninstall recipe, repair/reconfigure recipe. Keep mutating calls explicit.
6. Ensure recipe status can include source URL/date for official integration docs without requiring foundation/toolchains to know any provider or backend.

## Files

src/audiagentic/components/providers/descriptors/base.py
src/audiagentic/components/providers/services/recipes.py
src/audiagentic/components/providers/providers_api.py
src/audiagentic/components/providers/providers_mcp.py
src/audiagentic/config/components/providers.yaml
tests/unit/providers/

## Validation

- Provider recipe model can express Hindsight Codex hooks, Claude plugin, Copilot MCP+rule, OpenCode plugin config, Aider wrapper CLI, Continue context-provider+MCP/rules, and existing LSP provider support.
- Foundation toolchains remain unaware of provider IDs, MCP semantics, or components.
- Provider recipe API can report dry-run/planned commands before mutating.
- Existing provider lifecycle remains backward-compatible until migration stages land.

## Effort & Risk

Risk is over-abstracting. Keep first version small: typed lifecycle + registry + enough strategy metadata for status and dispatch; details stay in adapter modules.

## Notes

This is provider layer architecture. Do not add `hindsight` or `coding-lsp` strings to foundation.
