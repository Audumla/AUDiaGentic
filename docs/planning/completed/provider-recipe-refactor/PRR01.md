---
id: PRR01
order: 1
plan: plan-provider-recipe-refactor
state: completed
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

Audit complete. Key violations found:

1. foundation/toolchains/config_patcher.py:134-151: `add_mcp_entry` and `remove_mcp_entry` are MCP-specific helpers in a generic toolchain module. They're thin wrappers around `set_key`/`remove_key` with MCP-specific defaults.

2. foundation/toolchains/recipe_contract.py:1-18: Docstring names "MCP server registration, a hook, a plugin" as examples — these are domain concepts leaking into foundation.

3. foundation/toolchains/__init__.py: Exports all toolchain symbols; MCP helpers leak through.

4. components/memory/memory_api.py:197-207: `_trigger_surface_reconcile` calls `apply_provider_surfaces()` — memory orchestrates provider refresh.

5. components/memory/hindsight.yaml:27-29: `enabled-providers` option — memory chooses provider allowlist.

6. components/memory/hindsight_recipe.py: Uses `ConfigPatcher.add_mcp_entry/remove_mcp_entry` (MCP-specific), and owns a "Hindsight MCP config recipe" which is really provider/harness behavior.

Provider-side (correct ownership):
- descriptors/base.py: `McpConfigSpec`, `LanguageServersConfigSpec`, `on_lsp_enabled`, `receive_lsp_mcp` — provider-owned native capability behavior (correct)
- services/lsp_projection.py: Provider-owned LSP sync (correct)
- services/mcp.py: Provider-owned MCP config management (correct)

coding-lsp (correct ownership):
- lsp_recipe.py: Language server install as StepRecipe (correct)
- language_servers_sync.py: LSP projection to providers (correct)

Resolution plan:
- PRR03: Move MCP helpers out of foundation, into providers/services/mcp.py
- PRR02: Define provider-owned recipe contract types
- PRR04: Build Hindsight provider recipe matrix
- PRR05: Migrate Hindsight integration to provider-owned recipes
- PRR06: Align coding-lsp with provider recipe model
- PRR07: Add regression tests and docs
