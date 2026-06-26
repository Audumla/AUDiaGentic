---
id: PRR01
order: 1
plan: plan-provider-recipe-refactor
state: pending
validate-first: true
priority: P0
complexity: mid
---

# Audit and clean ownership boundaries in current recipe implementation

## Description

Review current `memory`, `providers`, `foundation/toolchains`, and `coding_lsp` recipe/provisioning implementation and remove boundary violations from the design before further feature work. Toolchains must remain generic and must not encode MCP, provider, harness, memory, or LSP semantics.

## Steps

1. Audit `src/audiagentic/foundation/toolchains/` for domain-specific language and behavior. Identify helpers that are truly generic (`set_key`, `remove_key`, command probes, artifact ownership) versus domain-specific (`add_mcp_entry`, `remove_mcp_entry`, recipe docs naming MCP/hooks/plugins as first-class semantics).
2. Audit `src/audiagentic/components/memory/` for remaining provider orchestration. `memory_api._trigger_surface_reconcile` and `enabled-providers` in `hindsight.yaml` are suspect because memory should not choose provider refresh policy or provider allowlists.
3. Audit provider-side LSP support (`McpConfigSpec`, `LanguageServersConfigSpec`, `on_lsp_enabled`, `receive_lsp_mcp`) as the existing reference for provider-owned native capability behavior.
4. Decide exact module boundaries: generic execution primitives stay in foundation workflow/toolchains; provider recipe registry and capability-specific provider integration contracts live under `components/providers`; component-specific backend export lives under the component.
5. Update or supersede existing tests that lock in wrong ownership, especially tests asserting MCP-specific helper behavior in `foundation/toolchains`.

## Files

src/audiagentic/foundation/toolchains/
src/audiagentic/components/memory/
src/audiagentic/config/components/memory/hindsight.yaml
src/audiagentic/components/providers/descriptors/base.py
src/audiagentic/components/providers/services/lsp_projection.py
tests/unit/foundation/toolchains/
tests/unit/memory/

## Validation

- Audit document or plan notes list each current violation and target owner.
- No new provider/Hindsight/MCP behavior is added to `foundation/toolchains`.
- Existing wrong-layer behavior is either scheduled for removal or explicitly justified as generic.
- Refactor sequence protects current LSP behavior while changing abstractions.

## Effort & Risk

Risk is mistaking generic config operations for provider recipes. Keep generic patch/probe primitives, move MCP naming and provider-capability orchestration out.

## Notes

Current known smells: `ConfigPatcher.add_mcp_entry/remove_mcp_entry`; `ProvisioningRecipe` docstring names MCP/hooks/plugins; `memory_api._trigger_surface_reconcile`; `hindsight.yaml` contains `enabled-providers`; `memory/hindsight_recipe.py` owns a Hindsight MCP config recipe.
