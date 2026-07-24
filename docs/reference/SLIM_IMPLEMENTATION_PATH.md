# Slim Implementation Path for Provider Automation Families

Each slim slice is a **real, working** piece of a plan item's implementation — no stubs.
Work accumulates: each slice advances a plan item toward completion. The old path
is replaced, not shadowed.

## Core Principle
For each function slice:
1. Define the RecipeDefinition (may already exist)
2. Register the real handler with ProviderAutomationRegistry
3. Route one real caller through `providers_api` → registry dispatch
4. Verify end-to-end with existing tests — behavior must match the old path
5. Delete the old direct path only after every caller is verified migrated

## Two Registration Patterns

Not every family goes through the ProviderAutomationRegistry. MA20 defines two
patterns, and the slim path must respect the distinction:

### Pattern A: Explicit code registration (ProviderAutomationRegistry)
For families where each provider has custom behavior that requires explicit
handler code. The provider declares the capability in its descriptor, and
`build_automation_registry` registers a per-provider handler.

**Example:** `cli-lifecycle` — each provider has different CLI install logic.

### Pattern B: Descriptor-backed generic service (no registry)
For families where the automation is purely driven by provider descriptor
declaration and typed adapter facts. The provider declares the capability,
and a generic service uses the descriptor facts to drive the operation.
No per-provider handler code is needed.

**Example:** `managed-mcp` — any provider with `mcp_config` can participate;
the `manage_mcp_entries` service reads the descriptor and syncs.

**Key rule:** A family is Pattern B only when semantics, ownership, modes, and
result behavior are identical across all providers. If one provider needs custom
behavior, it becomes Pattern A.

## The Signature Adaptation Problem

`RecipeHandler` is `Callable[[str, object, object | None], object]` — i.e.
`(mode, payload, ownership_scope)`. Real handlers need `project_root` to
read/write files. The solution is the **factory pattern**: a factory function
binds `project_root` (and any other per-provider context) via `functools.partial`
to produce a RecipeHandler-compatible closure.

The existing pattern from cli-lifecycle:
```python
# Factory binds project_root, returns RecipeHandler
handler = _make_cli_handler(provider_id, project_root)
# handler(mode, payload, ownership_scope) — project_root is closed over
registry.register(definition, handler)
```

Every new Pattern A family must follow this same pattern.

---

## Current State (2026-07-15, decisions resolved)

**Completed plan items:**
- MA12: CLI lifecycle (Pattern A, registered)
- MA21: Generated surfaces (Pattern A, registered with automation registry, 778 tests pass)
- MA23: Managed MCP (Pattern B, completed)
- MA24: Declared integration (Hindsight-owned, no providers_api)
- MA28: Language server projection (Pattern B, completed)
- MA29: LSP-MCP projection (Pattern B, callers migrated, old provision_provider_lsp_support deleted)
- MA30: Self-provided LSP (Pattern A, pi wired, 778 tests pass)
- MA31: Query/catalog normalization (completed)

**Active plan items with slim slices:**
- MA25: Plugin automation (Pattern A) — consolidate Memory, create family
- MA26: Codex/Pi Hindsight recipes (Pattern A, two families) — freeze contracts, migrate
- MA27: Hindsight family cutover — blocked by MA25, MA26
- MA28: Language server projection (Pattern B) — completed
- MA29: LSP-MCP projection (Pattern B) — freeze contracts
- MA30: Self-provided LSP (Pattern A) — freeze contracts, register handler
- MO02: Model projection (Pattern A) — contracts frozen, handler registered, pi wired

**Umbrella plan items (blocked by children):**
- MA02: Memory integration — blocked by MA25-MA27
- MA08: LSP entries — blocked by MA28-MA30
- MA22: Remove reconcile API — blocked by all families
- MA09: Audit gate — blocked by everything

---

## Slim Slices by Plan Item

### MA21: Generated Surfaces — Slice: Register with registry
**Plan item:** Migrate generated surfaces to recipe family
**Pattern:** A (per-provider handler)

**Current state:** Family contracts exist in `generated_surface_family.py`.
`_make_handler(project_root)` exists and returns a real handler.
`generated_surface_definition(provider_id)` exists. `generated_surface_family_contracts()`
exists and is loaded into `build_automation_registry`'s contract map.
`operate_provider_surface` calls `_make_handler` directly, bypassing the registry.

**Completed (2026-07-15):**
1. In `build_automation_registry`, registered each provider that declares `generated-surfaces` capability with real handler
2. Updated `providers_api.operate_provider_surface` to dispatch through the registry instead of calling `_make_handler` directly
3. 46 surface tests pass — the handler is the same, only the dispatch path changed
4. 7 families now in the registry (cli-lifecycle + generated-surfaces + model-projection + self-provided-lsp + others)
5. `LanguageServerEntry` re-exported from `providers_api` for backwards compatibility with `coding_lsp.language_servers`

**Risk:** Low. The handler is the same code, only the dispatch path changed.

**Verification:** Run `tests/unit/providers/test_surface_*.py`

**Result:** MA21 completes. 778 tests pass.

---

### MA25: Plugin Automation — Slice: Consolidate Memory, create family
**Plan item:** Migrate Hindsight provider plugin automation
**Pattern:** A (per-provider handler — plugins will be different per provider)

**Current state:** Only opencode declares `plugin_config`. `PluginConfigSpec` is generic
(reader/writer/remover). `manage_plugin_entry` exists but assumes a single plugin mechanism.
`HindsightPluginDesired` and `HindsightPluginDefinition` exist. Private recipe classes
and raw-row compatibility seams remain.

**Slim slice:**
1. Create `hindsight-plugin` family with `PluginRecipeRequest/Result`
2. Register per-provider handler for each provider with `plugin_config`
3. Complete private recipe consolidation in Memory
4. Remove raw-row compatibility seams
5. Verify `manage_plugin_entry` is the canonical entry point

**Risk:** Medium. Private recipe consolidation requires careful migration.

**Verification:** Run `tests/unit/providers/test_plugin_entry_*.py`, `tests/unit/memory/test_hindsight_*.py`

**Result:** MA25 advances toward completion. Enables MA27.

---

### MA26: Codex/Pi Hindsight Recipes — Slice: Freeze contracts, migrate Codex
**Plan item:** Migrate Codex and Pi Hindsight recipes to typed ownership
**Pattern:** A (two separate families: Codex file-based hooks, Pi subprocess npm install)

**Current state:** `CodexHindsightRecipe` exists with custom file operations (downloads
Python scripts, writes `~/.codex/hooks.json`, patches `~/.codex/config.toml`, writes
`~/.hindsight/codex.json`). Pi recipe exists with subprocess calls.

**Slim slice (Codex first, Pi non-executing):**
1. Create `hindsight-codex-recipe` family with `CodexRecipeRequest/Result`
2. Create `hindsight-pi-recipe` family with `PiRecipeRequest/Result`
3. Define `CodexHindsightDesired` — backend URL, bank ID, API key, hook scripts state
4. Define `PiHindsightDesired` — npm package state, subprocess execution result
5. Register per-provider handlers
6. Migrate Codex callers, delete raw `CodexHindsightRecipe` class
7. Pi: non-executing, evidence-only (no subprocess calls)

**Risk:** Medium. Codex config.toml is shared with other Codex settings; surgical
TOML editing must be preserved.

**Verification:** Run `tests/unit/memory/test_codex_*.py`, `tests/unit/memory/test_pi_*.py`

**Result:** MA26 advances toward completion. Enables MA27.

---

### MA27: Hindsight Family Cutover — Slice: Rewrite Memory orchestration
**Plan item:** Complete Hindsight family cutover and delete legacy recipes
**Pattern:** Umbrella (blocked by MA25, MA26)

**Current state:** Memory imports provider internals directly. `reconcile_hindsight`
and `build_hindsight_status_report` contain provider-id branches.

**Slim slice (after MA25 + MA26):**
1. Rewrite `reconcile_hindsight`/`build_hindsight_status_report` to call only
   providers_api family functions (no provider-id branch)
2. Memory retains backend desired values only; no provider mechanics
3. Delete matrix/factory/registry dispatch from Memory
4. Delete `services/recipes.py` and legacy provider recipe symbols after zero-use proof

**Risk:** Medium. Memory is a critical component. Must verify external summary
shape is preserved.

**Verification:** Run Memory/provider integration tests, architecture boundaries

**Result:** MA27 completes. Enables MA02.

---

### MA28: Language Server Projection — Slice: Family function, contracts, boundary fix
**Plan item:** Migrate language-server projection recipe family
**Pattern:** B (generic language_servers_config, three providers use identical mechanism)

**Current state:** `sync_language_servers_to_provider_configs()` iterates descriptors,
checks `language_servers_config`, calls `apply_managed_config_write()`/`apply_managed_config_remove()`.
Split apply/prune functions, action-string dispatch in `handle_lsp_provider_projection`.

**Completed (2026-07-15):**
- `LanguageServerEntry` moved to `providers/contracts/language_server_projection.py` (already done)
- `LanguageServerProjectionRequest/Result` frozen with typed contracts + `provider_id` field
- Added `language-server-projection` automation capability to opencode, codex, qwen descriptors
- Created `manage_language_servers` family function in `language_server_family.py` (Pattern B)
- Added `manage_language_servers_all` multi-provider operation through `providers_api`
- Exported through `providers_api` (single + all variants)
- Created `provider-language-server-projection-payload/v1` and `provider-language-server-projection-result/v1` JSON schemas
- Fixed reverse imports: `coding_lsp` now imports `LanguageServerEntry` through `providers_api`
- Migrated all coding-lsp callers: `sync_language_servers_to_providers` and `prune_language_servers_from_providers` use `manage_language_servers_all`
- Old split functions in `lsp_projection.py` are thin wrappers over the family function
- Architecture boundary test passes (no coding_lsp → providers internals imports)
- All 721 tests pass

**Completed (2026-07-15, continued):**
- Deleted old split functions: `sync_language_servers_to_provider_configs`, `prune_language_servers_from_provider_configs`
- Deleted action-string dispatch: `handle_lsp_provider_projection`, `_ACTION_HANDLERS`, individual `_handle_*` handlers
- Deleted dead event bus subscriber in `surfaces/observer.py` (`CODING_LSP_PROVIDER_PROJECTION` topic had no producer)
- Deleted `test_lsp_projection_dispatch.py` (tested deleted dispatch mechanism)
- Updated `test_lsp_enable_propagation.py` to test through `manage_language_servers`
- 719 tests pass, architecture boundaries pass

**Risk:** Medium. Moving `LanguageServerEntry` requires updating all provider adapters.

**Verification:** Run `tests/unit/providers/test_lsp_*.py`, architecture boundaries

**Result:** MA28 completes. Enables MA29.

---

### MA29: LSP-MCP Projection — Slice: Freeze contracts
**Plan item:** Migrate generic LSP-MCP projection recipe family
**Pattern:** B (generic mcp_config + receive_lsp_mcp flag)

**Current state:** `sync_generic_lsp_mcp_to_provider_configs()` iterates descriptors,
checks `mcp_config` + `receive_lsp_mcp` flag, calls `sync_managed_provider_mcp_subset()`.

**Completed (2026-07-15):**
- Frozen `LspMcpProjectionEntry/Request/Result/BatchResult` typed contracts with to_mapping/from_mapping serialization
- Created `provider-lsp-mcp-projection-payload/v1` and `provider-lsp-mcp-projection-result/v1` JSON schemas
- Created `manage_lsp_mcp_projection` family function in `lsp_mcp_projection.py` (Pattern B, no registry)
- Added `manage_lsp_mcp_projection` and `manage_lsp_mcp_projection_all` to `providers_api`
- 602 provider tests pass, 176 coding_lsp tests pass

**Completed (2026-07-15, continued):**
- Migrated LSP component callers: `language_servers_sync.py` now routes through `manage_lsp_mcp_projection_all`
- `sync_generic_lsp_mcp_to_providers()` and `prune_generic_lsp_mcp_from_providers()` in `language_servers_sync.py` are thin wrappers over the family function
- `coding_lsp_bootstrap.py`, `refresh.py`, `lsp_session_resolution.py` automatically benefit through the updated wrappers
- Updated test imports: `test_language_servers_sync.py` and `test_lsp_propagation_suppression.py` now monkeypatch `manage_lsp_mcp_projection_all`
- 778 tests pass

**Remaining:**
- Delete old split functions `sync_generic_lsp_mcp_to_provider_configs` / `prune_generic_lsp_mcp_from_provider_configs` from `lsp_projection.py` after all direct imports removed
- Update remaining test files that import old functions directly from `lsp_projection`

**Completed (2026-07-15, continued):**
- Deleted old `provision_provider_lsp_support` from `lsp_projection.py` (MA30 crossover)

**Risk:** Low. Generic service, no per-provider logic.

**Verification:** Run `tests/unit/providers/test_lsp_*.py`, `tests/unit/coding_lsp/test_language_servers_sync.py`

**Result:** MA29 advances toward completion. Enables MA30.

---

### MA30: Self-Provided LSP Support — Slice: Freeze contracts, register handler
**Plan item:** Migrate self-provided LSP support recipe family
**Pattern:** A (per-provider handler — only pi has on_lsp_enabled hook)

**Current state:** Only pi declares `on_lsp_enabled` hook, which runs a subprocess to
install the `npm:pi-lens` extension.

**Completed (2026-07-15):**
- Frozen `SelfProvidedLspMode/Request/Result` typed contracts with to_mapping serialization
- Created `provider-self-provided-lsp-payload/v1` and `provider-self-provided-lsp-result/v1` JSON schemas
- Created `self_provided_lsp_family.py` with FAMILY_ID, payload/result contracts, RecipeDefinition factory
- Created `self_provided_lsp_handler.py` with `_make_self_provided_lsp_handler` factory pattern (binds project_root)
- Registered self-provided-lsp handler in `build_automation_registry` for providers with `on_lsp_enabled`
- Added `manage_self_provided_lsp` to `providers_api` (dispatches through registry)

**Completed (2026-07-15, continued):**
- Added `self-provided-lsp` automation capability to pi.yaml descriptor
- Migrated `provision_provider_lsp_support` in `language_servers_sync.py` to route through `manage_self_provided_lsp`
- `lsp_config_api.py` and `test_provider_lsp_provision.py` benefit automatically through the updated wrapper
- Deleted old `provision_provider_lsp_support` from `lsp_projection.py` (no more direct callers)
- 778 tests pass

**Risk:** Low. Only pi uses this family.

**Verification:** Run `tests/unit/providers/test_lsp_*.py`

**Result:** MA30 completes. Enables MA08.

---

### MO02: Model Projection — Slice: Freeze contracts, register handlers
**Plan item:** Bind model projection through explicit provider handlers
**Pattern:** A (per-provider handler — each provider has unique model_entry_renderer)

**Current state:** model-source CRUD commits desired state only. Provider reconciliation
builds a typed request and calls `manage_model_projection`; the registered handler uses
each descriptor's `model_entry_renderer` and `supported_connectors` declarations.

**Completed (2026-07-15):**
- Frozen `ModelProjectionEntry/Request/Result` typed contracts with to_mapping/from_mapping serialization
- Created `provider-model-projection-payload/v1` and `provider-model-projection-result/v1` JSON schemas
- Created `model_projection_family.py` with FAMILY_ID, payload/result contracts, RecipeDefinition factory
- Created `model_projection_handler.py` with `_make_model_projection_handler` factory pattern
- Registered model-projection handler in `build_automation_registry` for providers declaring the capability
- Added `manage_model_projection` to `providers_api` (dispatches through registry)
- Created pi provider model config infrastructure: `read_pi_models/write_pi_models/remove_pi_model` reader/writer/remover
- Created `render_pi_model_entry` renderer for pi's models.json format
- Added `model-projection` automation capability, `model_config`, `model_entry_renderer`, `supported_connectors` to pi.yaml
- Moved provider reconciliation onto the typed public family operation
- Folded config inspection into model-projection status mode
- Removed the public sync/list/reload routes and CRUD apply/dry-run flags
- 602 provider tests pass, pi model-projection handler registered and discoverable

**Provider wiring status (evidence-gated):**
- pi: VERIFIED — custom model endpoint writes work via `~/.pi/agent/models.json`
- opencode: BLOCKED — config filename and winning container unresolved (MO03 path/container unification); descriptor notes "blocked"
- codex: BLOCKED — project-scope precedence NOT verified (RV353); global `~/.codex/config.toml` may override project `.codex/config.toml`
- qwen: N/A — single auth-type switch, no custom endpoint catalog; not a projection target

**Remaining:** None for the shared family boundary. Additional provider wiring remains
evidence-gated and must only be added when a provider exposes a verified, useful model
projection surface.

**Risk:** Medium. Model projection is a critical path. Must verify parity.

**Verification:** Run `tests/unit/providers/test_model_*.py`

**Result:** MO02 completes. Pi is wired; unsupported providers remain deliberately
unregistered rather than accumulating speculative writers. Enables MA22.

---

### MA02: Memory Integration — Umbrella, blocked by MA25-MA27
**Plan item:** Delegate memory integration intent through providers public API
**Pattern:** Umbrella (no single function, family-specific calls through providers_api)

**Current state:** Memory imports provider internals directly. MA27 rewrites
`reconcile_hindsight`/`build_hindsight_status_report` to call only providers_api
family functions (no provider-id branch).

**Slim slice (after MA27):**
1. Memory retains backend desired values only; no provider mechanics
2. Delete matrix/factory/registry dispatch from Memory
3. Delete `services/recipes.py` and legacy provider recipe symbols after zero-use proof

**Risk:** Medium. Memory is a critical component. Must verify external summary
shape is preserved.

**Verification:** Run Memory/provider integration tests, architecture boundaries

**Result:** MA02 completes.

---

### MA08: LSP Entries — Umbrella, blocked by MA28-MA30
**Plan item:** Adopt managed ownership for provider LSP entries
**Pattern:** Umbrella (no single function, family-specific calls through providers_api)

**Current state:** LSP component imports provider internals directly. MA28-MA30
provide family-specific operations in providers_api.

**Slim slice (after MA28-MA30):**
1. LSP component migrates callers to the specific family functions
2. Delete reverse imports, action-string dispatch, old projection routes

**Risk:** Medium. LSP is a critical component.

**Verification:** Run LSP/provider boundary tests

**Result:** MA08 completes.

---

### MA22: Remove Reconcile API — Complete (2026-07-24)
**Plan item:** Remove universal provider reconcile API
**Pattern:** Cleanup (was blocked by MA25, MA26, MA27, MA28, MA29, MA30, MO02, SH07, MA17 — all now complete)

**Final state:** `reconcile_provider`/`reconcile_all_providers` removed from providers_api's
public exports and the ag-providers-mgmt MCP tool surface. The one real internal
caller (commands/launch.py's on-launch reconciliation) already called
`services.lifecycle.reconcile_all_providers` directly — the retained private
provider-owned composition path — so no caller migration was needed beyond
that.

**Verification:** tests/unit/providers/ (367 tests) and
tests/unit/foundation/toolchains/test_architecture_boundaries.py green.

**Result:** MA22 complete. Enables MA09.

---

### MA09: Audit Gate — Blocked by everything
**Plan item:** Close managed mutation audit and integration gates
**Pattern:** Audit (blocked by MA22, MA17, MA13)

**Slim slice (after everything):**
1. Run full test suite — no regressions
2. Verify no provider internals are imported by requester components
3. Confirm every Pattern A family is registered and routed through the registry
4. Confirm every Pattern B family uses providers_api as the canonical entry point
5. Verify exact MA16 22-export classification and target disposition
6. Verify six queries are non-mutating, six resource commands use no modes/recipes
7. Verify reconcile and all obsolete routes/flags/aliases/shims/tests absent

**Result:** MA09 completes. Program done.

---

## Execution Order

**Ready now (no blockers):**
1. MA21: Register generated surfaces with registry (low risk)
2. MA25: Consolidate Memory, create plugin family (medium risk)
3. MO02: Freeze contracts, register handlers (medium risk)

**After MA25 + MA26:**
5. MA27: Rewrite Memory orchestration (medium risk)

**After MA28:**
6. MA29: Freeze LSP-MCP contracts (low risk)

**After MA29:**
7. MA30: Self-provided LSP handler (low risk)

**After MA25 + MA26 + MA27:**
8. MA02: Memory integration completes

**After MA28 + MA29 + MA30:**
9. MA08: LSP entries completes

**After all families (MA25, MA26, MA27, MA28, MA29, MA30, MO02):**
10. MA22: Remove reconcile API (high risk)

**After MA22 + MA17 + MA13:**
11. MA09: Audit gate

---

## Success Criteria
For each slice:
- ✅ Real RecipeDefinition defined and validated (Pattern A) or providers_api canonical (Pattern B)
- ✅ Real handler registered (Pattern A) — not a stub, does actual work
- ✅ Factory function binds project_root, returns RecipeHandler-compatible closure
- ✅ One real caller migrated through providers_api → registry (Pattern A) or providers_api (Pattern B)
- ✅ Existing test suite passes (no regressions)
- ✅ Old direct path deleted only after every caller is verified migrated
- ✅ End-to-end behavior matches the old path

---

## Provider Capability Landscape

| Provider | plugin_config | language_servers_config | mcp_config | on_lsp_enabled |
|----------|---------------|------------------------|------------|----------------|
| opencode | YES | YES | YES | NO |
| codex | NO | YES | YES | NO |
| qwen | NO | YES | YES | NO |
| claude | NO | NO | YES | NO |
| pi | NO | NO | YES | YES |
| cline | NO | NO | YES | NO |
| roo | NO | NO | YES | NO |
| goose | NO | NO | YES | NO |
| gemini | NO | NO | YES | NO |
| copilot | NO | NO | YES | NO |
| continue | NO | NO | YES | NO |
| openhands | NO | NO | YES | NO |
| antigravity | NO | NO | YES | NO |
| local_openai | NO | NO | NULL | NO |

---

## Resolved Decisions

1. **MA25: Pattern A** — plugins will be different per provider. Per-provider handler required.
2. **MA26: Pattern A, two families** — Codex (file-based hooks) and Pi (subprocess npm install) are fundamentally different. Separate families.
3. **MA28: Pattern B** — Three providers (opencode, codex, qwen) use identical `language_servers_config` mechanism.
4. **MA29: Pattern B** — Generic `mcp_config` + `receive_lsp_mcp` flag. No per-provider custom logic.
5. **MA30: Pattern A** — Only pi has `on_lsp_enabled` hook (subprocess to install `npm:pi-lens`). Per-provider handler required.
6. **MO02: Pattern A** — Each provider has unique `model_entry_renderer` callable and `supported_connectors` tuple. Per-provider handler required.

---

## Remaining Blockers

1. **MA26: Codex config schema freeze** — `CodexRecipeRequest/Result` must be defined before handler code. The config format is known from `codex_recipe.py`:
   - `~/.codex/hooks.json` — event-driven hook structure
   - `~/.codex/config.toml` — `[features] hooks = true`
   - `~/.hindsight/codex.json` — Hindsight backend config
   - `~/.hindsight/codex/scripts/` — downloaded Python hook scripts

2. **MA28-MA30: Three separate schema freezes** — Typed request/result pairs must be defined before handler code (schemas can be drafted from current code, but must be reviewed and frozen).

3. **MA28: Reverse import removal** — `coding_lsp.LanguageServerEntry` is imported by provider adapters (opencode, codex, qwen). Must be moved to the family boundary before MA28 can proceed.

4. **MO02: Model projection schema freeze** — `ModelProjectionRequest/Result` must be frozen. The payload mirrors `MaterializedModelEntry` from `services/models.py`. The result shape follows `sync_managed_config` pattern.
