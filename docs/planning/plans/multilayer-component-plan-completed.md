# Multi-Layer Component Plan — Completed Items

> **Archive of completed work** from `multilayer-component-plan.md`.
> Moved here to slim the active plan. Open items remain in the active plan.

---

## Implementation Status — Completed Entries

### Completed 2026-06-20 (small cleanups)

* **A22 — done.** `coding_lsp/lsp_api.py` now uses module-level `logger` instead
  of inline `logging.getLogger(__name__)`.
* **A15 — partial (done for reconcile.py and runner.py).**
  `providers/services/reconcile.py` now logs `logger.warning` with `exc_info=True`
  on background reconcile failure (was silent `pass`).
  `runtime/update/runner.py` temp-file cleanup blocks now log `logger.debug` with
  `exc_info=True` (was silent `pass`).
  `foundation/components/hooks.py` was already acceptable (safe default + downstream
  warning logging).
  `ledger/sync.py` now catches only `OSError` for PID liveness checks instead of
  swallowing all exceptions.
* **L1-L3 — resolved.** `docs/examples/` fixtures are generic. Remaining provider
  names in `ARCHITECTURE_STANDARDS.md` are intentional anti-pattern illustrations.
* **C2 Docker validation — still outstanding.** Test exists at
  `tests/integration/coding_lsp/test_provider_lsp_e2e.py` with Dockerfile at
  `tests/docker/Dockerfile.provider-lsp-e2e`. Requires CI/Docker with raised
  timeout and `AUDIAGENTIC_DOCKER_TESTS=1`.

### Full architecture standards review — 2026-06-21

Comprehensive review against all 10 sections of `docs/ARCHITECTURE_STANDARDS.md`.

* **A18 — scope confirmed (3 files, validated 2026-06-21).**
  `providers/providers_mcp.py:42`, `core/project/project_mcp.py:38`,
  `core/session/session_mcp.py:43` construct `FastMCP(...)` directly.
  `optional/coding_lsp/lsp_mcp.py` already uses `mcp_server(__name__)` — compliant.
* **A14 — scope refined (validated 2026-06-21).** Initial review found 40 total
  `raise ValueError` sites, ~25 at public boundaries. Completed follow-up:
  `foundation/features/options.py`, `foundation/components/loader.py`,
  `foundation/components/dependencies.py`, `foundation/features/registry.py`,
  `optional/coding_lsp/language_registry.py`, and
  `foundation/workflow/state_machine.py` now raise `AudiaGenticError` with
  canonical codes. Remaining candidates are workflow action/propagation helpers,
  path/config validation seams, and validator CLI internals that should be
  classified before editing.
  Additional follow-up: workflow action rendering/execution, workflow propagation
  engine/config/rules/healing, workflow id generation, package-root lookup,
  provider CLI workflow action validation, and shared rig binary updater failures
  now also use canonical `AudiaGenticError`. Remaining raw built-in exceptions
  are classified as validator internals or adapter-local parser/renderer
  validation.
* **A25 — cli_io module (done).** Introduced `cli_io` with `print_json`,
   `print_message`, `print_error` to unify CLI/harness output. 80+ sites converted:
   `runtime/rig/embedded/binaries.py` (~14), `runtime/rig/embedded/cli.py` (~12),
   `runtime/harness/pi/runner/agent_run.py` (~15), `runtime/update/prompt.py` (~9),
   `runtime/harness/pi/install/patches.py` (10 via `_c._print()`),
   `runtime/harness/pi/install/__init__.py` (8 via `_c._print()`),
   `commands/launch.py` (~8), `commands/provider_prompt.py` (~4),
   `core/session/session_mcp.py:15`, `core/project/project_mcp.py:11`,
  `optional/providers/providers_mcp.py:11`,
  `runtime/harness/opencode/install/__init__.py` (1 via `_c._print()`).
* **A26 — SystemExit in library code (11 sites, confirmed).**
  `foundation/io.py:62,68` (library), `foundation/config.py:18` (library),
  `runtime/rig/models.py:38,54,60` (library),
  `runtime/harness/__init__.py:57,66` (library),
  `runtime/harness/pi/install/__init__.py:68,73` (library),
  `runtime/harness/opencode/install/__init__.py:126,162` (library),
  `optional/providers/providers_mcp.py:12` (`sys.exit(1)` at module level),
  `runtime/rig/embedded/binaries.py:175,181,217` (`sys.exit(1)` in library).
  Completed follow-up: `foundation/io.py`, `foundation/config.py`,
  `foundation/paths/resolution.py`, and `foundation/system/process.py` now raise
  canonical `AudiaGenticError` values instead of exiting the process. Remaining
  foundation `SystemExit` sites are validator CLI wrappers.
  Additional follow-up: generic harness/rig shared helpers now also return
  `AudiaGenticError` instead of exiting: `runtime/harness/config.py`,
  `runtime/harness/__init__.py`, `runtime/rig/http.py`,
  `runtime/rig/models.py`, `runtime/rig/embedded/config.py`, and
  `runtime/harness/rig.py`. `launcher.main()` is now the CLI boundary that
  reports `AudiaGenticError` cleanly.
  Final follow-up: embedded rig resolution/process/launch helpers, rig binary
  update failures, Pi/Opencode harness install validation, and Pi/Opencode runner
  validation now also raise canonical `AudiaGenticError`. Remaining raw
  `SystemExit`/`sys.exit()` hits are intentional CLI/MCP entrypoint exits or
  update handoff exits.
* **A27 — God objects (reviewed 2026-06-21: NOT violations, withdrawn).**
  Original review counted functions as responsibilities. Re-review:
  `runtime/lifecycle/components.py` (260 lines) — 1 responsibility (component
  lifecycle CRUD: install/uninstall/enable/disable; private helpers are marker I/O
  for same domain). `runtime/rig/embedded/binaries.py` (236 lines) — 1
  responsibility (single `update_binaries()` pipeline; all private functions are
  pipeline steps). `runtime/harness/pi/install/__init__.py` (187 lines) — 1
  responsibility (Pi harness install/uninstall; MCP config functions are thin
  2-line wrappers). All three are cohesive modules. No decomposition needed.
* **A28 — Platform coupling (reviewed 2026-06-21: NOT violations, withdrawn).**
  All four cited files are already scoped to their respective harness/rig:
  `runtime/harness/pi/` hardcodes Pi-specific paths (acceptable — Pi harness
  module), `runtime/harness/opencode/` hardcodes `opencode` CLI (acceptable —
  Opencode harness module), `runtime/rig/embedded/` hardcodes `llama-server`
  (acceptable — embedded rig module). Rule 4 prohibits coupling in shared layers,
  not in harness-specific modules. The shared dispatch layer
  (`runtime/harness/__init__.py`) correctly imports by convention.
* **A15 — except Exception: scope (reviewed 2026-06-21: NOT violations, withdrawn).**
  11 `except Exception:` blocks in `runtime/update/checker.py` (7),
  `foundation/event/event_store.py` (3), `foundation/event/event_config.py` (1) —
  all at external boundaries (I/O, network, file parsing, third-party). This is
  the acceptable pattern. No silent `pass` blocks found.
* **Rule 5 — __all__ enumeration (reviewed 2026-06-21: NOT a violation, withdrawn).**
  `optional/providers/adapters/__init__.py:26` — `__all__` is dynamically computed
  from `pkgutil.iter_modules(__path__)`. The standard prohibits *maintained*
  enumerations; dynamic discovery that populates `__all__` is compliant.

---

## Execution Plan — Completed Items

### Step 2 — Fix foundation layer inversions + unify error handling

**Done: A8** — YAML helpers moved to `foundation/io.py`, `foundation/config.py`,
`foundation/home.py`, `foundation/paths/package.py`. Runtime re-exports for
compatibility. **Done: C11** — `validate_with_schema()` added to
`foundation/contracts/schema_registry.py`; canonical-schema callers migrated.
**Done: A13** — `EventBusError`, `LspError`, `LspServerError` now subclass
`AudiaGenticError` with canonical codes. **Done: A14 for shared/public seams** —
feature/component option and descriptor validation, dependency workflow
validation, LSP language descriptor validation, feature registry invariants,
workflow state/action/propagation validation, path/package lookup, provider CLI
workflow guard, and shared rig binary updater failures now use canonical
`AudiaGenticError` codes. Remaining raw built-in exceptions are validator
internals or adapter-local parser/renderer validation. Core project/session,
release-please, component_server, and LSP bridge converted.
**Done: A15** — `reconcile.py`, `runner.py`, `hooks.py`, `ledger/sync.py` all
fixed. Remaining `except Exception:` blocks are at external I/O boundaries
(acceptable per standard). Gate: foundation feature/component/contract tests
plus runtime config compatibility.

### Step 3 — Close provider capability modeling

**Done: A4** — provider schemas validate by identifier
pattern, no longer enumerate provider IDs. **Done: A5** — provider aliases
moved to `ProviderDescriptor.prompt_aliases`, registry exposes
`provider_alias_map()`. Gate: provider unit/integration suites and parity
output.

### Step 7 — Remove central capability edit points

**Completed:** provider adapters are package-discovered and harness
types import by convention. Rename/model VS Code extension support as generic host capabilities
without building a broad multi-editor framework before a second host exists
(A1 follow-up). **Completed M11 (2026-06-21):** shipped dependency YAML no
longer uses `custom:` Python dotpaths; the existing dependency resolver gained
small generic probe forms (`all-binaries:`, `command:`, `toolchain:uv`)
instead of adding a new probe registry. Gate: provider discovery, harness
selection, and dependency/probe tests.

### Step 8 — Consolidate duplicated patterns

**MCP server construction (A18) — done 2026-06-21.** Added
`run_mcp_server(server, label)` to `foundation/mcp/component_server.py` and
migrated the 3 outlier servers (`session_mcp`, `project_mcp`,
`providers_mcp`) off direct `FastMCP(...)` construction onto
`mcp_server(__name__)` + `run_mcp_server()`. This also removed per-module
`try/except ImportError: print(...); sys.exit(1)` boilerplate (A25/A26
reduction) — `Context`/`FastMCP` are imported from `component_server`, whose
import guard is the single source — and replaced `providers_mcp`'s local
`_server_instructions`/`_tool_description` with the foundation
`server_instructions`/`tool_description` helpers. `lsp_mcp`'s FastMCP name is
now config-resolved (`ag-lsp`) instead of the hardcoded `lsp-mcp`. The smoke
contract is preserved (`build_server()` for the 3 decl-driven servers,
module-level `mcp` for `lsp_mcp`). Gate: MCP/component_server/provider unit
suites green; touched-file Ruff clean. (The 2 `language_servers_sync`
projection failures on this branch are pre-existing WIP, unrelated to A18.)

**MCP config format adapters (A19) — closed as already-satisfied 2026-06-21.**
The generic adapter A19 asked for already exists as
`McpConfigSpec(reader, writer, remover, format, refresh_mode)`: each
descriptor plugs format-specific callables into the common spec, and JSON-form
adapters already share `foundation/mcp/json_format.py`. The remaining
`codex` (nested TOML tables) and `goose` (YAML extensions list) serializers
are genuinely format-specific, not copy-paste duplicates; wrapping them in a
further `McpConfigAdapter` protocol would add ceremony with no dedup payoff.
No code change made.

**Duplicate dataclasses (A20) — done 2026-06-21 via a tiered base.**
`SurfaceFile` now aliases the foundation `ComponentFile` (field-identical;
surfaces use only the `MODE_*` lifecycle values `create-if-missing` /
`required-managed`). For the descriptors, introduced a shared **tier** rather
than a forced merge: `FileBearingDescriptor` (foundation
`components/base.py`, `frozen=True, kw_only=True`) owns the common
file-bearing shape — `display_name`, `description`, `detection_marker`,
`files`, `type`. `ComponentDescriptor(FileBearingDescriptor)` and
`SurfaceDescriptor(FileBearingDescriptor)` each add only their own identity
(`component_id` / `descriptor_id`) and domain fields, so surfaces share
structure without inheriting component-only fields (`mcp_servers`, `scope`,
`core`, `implementation_cardinality`, …). `kw_only` is safe: all descriptor
construction is keyword-only (verified), with no positional / `astuple` /
`fields()` reliance. The feature-layer family
(`Feature`/`Implementation`/`Binding` descriptors) was given its own parallel
tier (`foundation/features/base.py`): `ConfigurableDescriptor` (`parent`,
`options_schema`, `raw`) is the base for all three;
`LabeledDescriptor(ConfigurableDescriptor)` adds the user-selectable-unit
fields (`display_name`, `description`, `dependencies`) shared by
`FeatureDescriptor` and `ImplementationDescriptor`; `BindingDescriptor`
branches off `ConfigurableDescriptor` directly because it is derived — no
presentation, and it *references* dependencies (`uses_dependencies`) rather
than declaring them. Each leaf keeps its own `key` property and id field
(`feature_id` / `implementation_id`), so no renames were needed and
`registry.register()` `isinstance` dispatch is unchanged. Gate:
foundation/component/surface/loader/registry + coding-lsp + provider unit
suites green; Ruff clean. (The stale `planning`-component and `uninstall`
return-shape failures in `tests/dev/foundation/test_component_registry.py`,
and the 2 `test_lsp_propagation_suppression` agent-lsp projection failures,
are pre-existing branch WIP unrelated to this refactor.)

### Step 9 — Logging infrastructure cleanup

**Done: A22** — `coding_lsp/lsp_api.py` now uses module-level `logger`.
**A25: cli_io module (done).** Introduced `cli_io` with `print_json`, `print_message`, `print_error` to unify CLI/harness output. 80+ sites converted across CLI, harness, update, rig, contracts, and providers.
findings above. **A26: done.** Shared foundation YAML/config/path/process
helpers, generic harness/rig config/model/health/launch helpers, embedded rig
resolution/process helpers, rig binary updater failures, and harness install/run
validation now return canonical `AudiaGenticError` instead of raising
`SystemExit`. Remaining raw exits are intentional CLI/MCP entrypoint or update
handoff boundaries.

**Structured context (A23) — reviewed 2026-06-21:** logging infrastructure
already preserves `extra={}` fields in JSON diagnostic logs; no new logging
framework is needed. Use canonical keys `component_id`, `provider_id`,
`item_id`, `event_type`, `operation`, `tool_name`, `duration_ms`, and
`project_root`. Implement in small batches: event bus, workflow propagation,
lifecycle/component hooks, provider LSP projection, and MCP tool boundary.

**Sensitive data audit (A24) — completed 2026-06-21:** Claude execution
failures now report stdout/stderr lengths instead of raw stream content, and
`report_error()` redacts sensitive structured details plus common secret
patterns before returning MCP error envelopes.

---

## Stage 0 — Foundation Core (Done)

Implemented under `src/audiagentic/foundation/features/`:

* Descriptor models: `FeatureDescriptor`, `ImplementationDescriptor`,
  `BindingDescriptor`, `OptionSchema`, state and resolved-config dataclasses
* Loader support for `type: feature`, `type: implementation`, and `type: binding`
* Registry support for features, implementations, and bindings
* State store at `.audiagentic/config/runtime/features.yaml`
* Option validation/default resolution
* Implementation lifecycle helpers, including exclusive-cardinality behavior
* Component loader dispatch so component config trees can contain feature,
  implementation, and binding descriptors
* Component descriptor metadata field: `implementation-cardinality`

Validation completed:
* Added foundation tests for descriptor load, registry lookup, state,
  resolution, option validation, and exclusive implementation switching
* Foundation/lifecycle/contract gate passed during implementation

---

## Stage 1 — Agent Jobs (Done)

* Converted shipped action descriptors: `ag-implement`, `ag-plan`, `ag-review`
* Each action declared as `type: feature parent: agent-jobs kind: action`
* Old `type: action` descriptor path rejected
* Provider tag loader projects action features into existing `ActionDescriptor` shape
* Component config references action feature descriptors directly

Validation:
* Added `tests/unit/providers/test_action_feature_loader.py`
* Stage 1 runnable gate passed

---

## Stage 2 — Constructive LSP Migration (Done)

* `coding-lsp.yaml` declares `implementation-cardinality: exclusive`
* Added implementation descriptors: `ag-lsp`, `agent-lsp`
* Converted language descriptors to `type: feature parent: coding-lsp kind: language`
* Current shared language features: `python`, `typescript`, `rust`, `cpp`
* Added bindings for both implementations across all current language features
* LSP management can list and select implementations
* Exclusive implementation state persisted in `features.yaml`
* Provider MCP projection is implementation-aware
* Language enable/disable mirrors into feature state
* Active implementation dependencies participate in dependency install/status
* Language feature options via `server-settings`
* LSP status reports active implementation, per-language state, feature options, missing binaries

Current bridge state:
* `features.yaml` is the user-intent store
* `.coding-lsp/lsp.json` remains as generated runtime cache/projection
* `language_registry.py` still exists as an LSP-specific adapter over registered
  language feature descriptors

Validation: `699 passed, 12 skipped`. Touched-file Ruff checks passed.

### Stage 2 Decommission (Done)

* Binding writer registry prerequisite complete
* Runtime servers derived from `features.yaml` + active implementation/bindings
* No importer built for this greenfield/template stage
* Tests rewritten to use feature state and bindings
* `language_registry.py` no longer owns a YAML catalog; it adapts registered
  coding-lsp `FeatureDescriptor`s into runtime `LanguageSpec`s

---

## Stage 3 — Completed Items

### Architectural integrity review findings — accepted (completed)

**Critical / Stage 3-5 blockers**

* **C1 — fixed.** `foundation/contracts/canonical_ids.py` is now **component-free**.
  Provider-id discovery moved to `providers.descriptors.registry.canonical_provider_ids()`.
  Dead `get_canonical_ids` + `CanonicalIds` removed. Component caller imports from
  providers component directly. `validate_ids.scan_paths` scanner core is
  component-free via injected `provider_ids`.
  **Completed 2026-06-20:** provider-aware CI/CLI moved to
  `components/optional/providers/validate_ids.py`; foundation CLI no longer
  loads provider IDs unless explicitly passed with `--provider-id`.

* **C2 — done.** `lsp.json` is now a pure regenerated cache. `lsp_config_api`
  no longer read-modify-writes individual lsp.json entries. New
  `_regenerate_lsp_cache(project_root)` writes the whole cache as a projection of
  `resolve_active_runtime_servers`. `add_language` / `remove_language` mutate only
  feature state then regenerate. Tests updated, host gate 854 passed.
  * **Attempted 2026-06-20: Docker e2e run completed, infrastructure blocker found.**
    3 tests passed, 22 tests errored in fixture setup due to Docker volume mount
    stat deadlock. Infrastructure issue, not C2 regression.

* **C3 — done.** LSP generic MCP projection is descriptor-driven.
  `ag-lsp.yaml` and `agent-lsp.yaml` declare `projection.generic-mcp` metadata.
  `language_servers_sync.py` derives managed IDs and entries from descriptors.

* **C4 — done.** Binding loader no longer defaults `feature-kind` to `language`.
  Missing values fail descriptor load.

* **C5 — done (deleted).** `providers/surfaces/base.py` dead code
  `tag_alias_examples` / `provider_alias_examples` removed outright.

**Medium / planned cleanup (completed)**

* **M1 — done.** `runtime_resolver.default_lsp_implementation()` sources default
  from descriptor metadata.
* **M2 — done.** `discover_language_servers` discovers from `resolve_active_runtime_servers`.
* **M3 — done.** `config_status` cache fields nested under `projection_cache`.
* **M4 — done.** `coding-lsp.yaml` instruction text updated.
* **M9 — done.** Feature state is the single enablement authority.
  `providers.yaml.enabled` removed entirely.
* **M11 — done.** Shipped dependency probes no longer use Python dotpaths.

**Low / opportunistic cleanup (completed)**

* **L1-L3 — resolved.** Documentation examples are generic.
* **L4 — done.** `lsp_api.resolve_project_root` no longer treats `lsp.json` as project marker.
* **L6 — done.** Removed unused `_AGENT_LSP_IMPLEMENTATION_ID` constant.

### Architecture review findings (completed)

* **A1 — shared provider registry owns VS Code host probing.**
  **Completed 2026-06-20:** VS Code extension discovery/status moved to
  `providers/services/host_capabilities.py`.
  **Completed 2026-06-21:** provider descriptors now expose generic
  `host_capabilities` using `HostCapability(host, capability_id, display_name)`.

* **A2 — runtime lifecycle imports provider internals for MCP projection.**
  **Completed 2026-06-20:** provider-specific MCP projection moved into the
  providers component and triggered through lifecycle/event-bus subscribers.

* **A3 — runtime harness registers itself through provider internals.**
  **Completed 2026-06-20:** removed unused runtime-owned descriptor module.

* **A4 — provider schemas still hardcode provider IDs.**
  **Completed 2026-06-21:** schema now validates by lowercase hyphenated identifier pattern.

* **A5 — prompt syntax still hardcodes provider aliases.**
  **Completed 2026-06-21:** aliases moved to `ProviderDescriptor.prompt_aliases`.

* **A6 — done.** LSP generic projection uses implementation metadata.

* **A7 — foundation/provider canonical ID validation remains inverted.**
  **Completed 2026-06-20:** foundation validation accepts injected provider IDs.

* **A8 — foundation imports runtime config helpers.**
  **Completed 2026-06-21:** YAML helpers moved to `foundation/io.py`; layered
  config to `foundation/config.py`; shared home/path helpers to `foundation/home.py`
  and `foundation/paths/package.py`. Runtime modules re-export for compatibility.

* **A9 — provider adapter registration uses duplicated import lists.**
  **Completed 2026-06-21:** `providers/adapters/__init__.py` discovers
  package-local adapter packages via `pkgutil.iter_modules()`.

* **A10 — harness type registry is a small central edit point.**
  **Completed 2026-06-21:** harness facade imports by validated convention.

### Event/contribution migration scan (completed)

* **E1 — LSP provider projection.**
  **Completed 2026-06-20:** LSP projection functions publish
  `coding-lsp.provider-projection.sync` events. Provider-owned
  `providers/services/lsp_projection.py` handles provider descriptors,
  enabled-provider resolution, provider hooks, and config writes.

* **E2 — Provider reconcile should not call runtime MCP sync helper.**
  **Completed 2026-06-20:** provider reconcile publishes
  `lifecycle.component.mcp.sync` events after registering component observers.

* **E4 — Launcher/component side effects.**
  **Completed 2026-06-21:** `commands/component.py` no longer owns its own
  harness refresh/reload helper and no longer imports runtime lifecycle mutation
  functions directly. Component install/uninstall/enable/disable now route
  through the core project component API, where harness refresh behavior is
  already centralized. Direct CLI command dispatch remains direct; no extra
  event layer was added.

* **C8 — done.** Baseline sync owns copying, not component rendering.

* **C9 — Foundation ID validation needs injected/contributed IDs.**
  **Completed 2026-06-20:** foundation `scan_paths` validates provider IDs
  only when an allowed provider ID set is injected.

* **C10 — Harness/provider MCP JSON helper reuse.**
  **Completed 2026-06-20:** standard MCP JSON helpers moved to
  `foundation/mcp/json_format.py`.

* **C11 — Shared schema validation helper.**
  **Completed 2026-06-21:** `validate_with_schema()` added to
  `foundation/contracts/schema_registry.py`.

### Error handling review findings (completed)

* **A13 — parallel exception hierarchies.**
  **Completed 2026-06-21:** `EventBusError`, `LspError`, `LspServerError` now
  subclass `AudiaGenticError` with canonical codes.

* **A14 — built-in exceptions at public boundaries.**
  **Partial fix 2026-06-21:** converted core project/session public helper
  `RuntimeError`s, release-please install `ValueError`,
  `component_server.project_root_from_env`, and LSP bridge "already running"
  failure to `AudiaGenticError`-based errors.
  **Scope refined 2026-06-21:** ~25 public-boundary `ValueError` sites remain;
  ~15 internal sites confirmed acceptable.

* **A15 — silent error swallowing.**
  **Done 2026-06-21:** all four targeted files fixed. Remaining `except Exception:`
  blocks are at external I/O boundaries — acceptable per standard.

* **A16 — hardcoded virtual asset paths in baseline sync — done.**
  Virtual asset chain removed from `baseline_sync.py`.

* **A17 — hardcoded contribution ID branches in baseline sync — done.**
  Contribution ID chain removed.

* **A18 — MCP server construction bypasses foundation factory — done 2026-06-21.**
  3 outlier servers migrated to `mcp_server(__name__)` + `run_mcp_server()`.

* **A19 — MCP config format handlers copy-pasted across providers.**
  Closed as already-satisfied. `McpConfigSpec` already exists.

* **A20 — Duplicate dataclasses — done 2026-06-21 via a tiered base.**
  `FileBearingDescriptor` and `ConfigurableDescriptor` tiers introduced.

* **A22 — Logging — inline logger creation — Done 2026-06-20.**

* **A23 — Logging — unstructured context — reviewed 2026-06-21.**
  5 implementation batches completed: event bus, workflow propagation,
  lifecycle/component hooks, provider LSP projection, MCP boundary.

* **A24 — Logging — sensitive data in error details — done 2026-06-21.**

### Code cleanse — 2026-06-20

* **Done — removed 2 pure-dead foundation functions** (zero references):
  `registry.all_implementation_features`, `lifecycle.reset_implementation_feature_option`.
* **Done — A22 logging cleanup.**
* **Done — A15 silent swallow cleanup (partial).**
* **Layering verified clean.** `foundation/features/*` imports no component modules.
* **Finding — foundation lifecycle write API is largely test-only (decision
  needed, not auto-removed).**

### Projection enabled-gating decision — DECIDED: enabled-aware

Projection (MCP, surfaces, LS, skills) targets only *enabled* providers, via the
resolver. Self-healing — every sync writes managed entries to enabled providers
and *prunes* them from disabled providers.

### Impl-scoping approach decision

**Approach A — programmatic derivation from `ProviderDescriptor` (recommended, chosen).**
Generate impl-scoped `FeatureDescriptor`s at registration time from the
existing Python `ProviderDescriptor` fields.

### Hardcoded lists — additional edit points (review supplement)

| Finding | Maps to | Notes |
|---------|---------|-------|
| Provider adapter import lists (15 providers, 2 files) | A9 | Already tracked |
| Harness `_REGISTRY` dict (2 types) | A10 | Already tracked |
| Provider alias dict in `prompt_syntax.py` (9 of 17) | A5 | Already tracked |
| Component ID constants + frozensets in `ids.py` | — | Not a defect |
| Virtual asset paths in `baseline_sync.py` | A16 | Done |
| Contribution ID branches in `baseline_sync.py` | A17 | Done |
| Tool restriction policy in `claude/restrictions.py` (5 tags) | C12 | Adapter-local |
| Release types in `release_please/install.py` (6 types) | — | Low severity |
| Capability kinds in `feature_mapping.py` (4 kinds) | — | Not a defect |
| Job control actions in `launcher.py` (3 actions) | — | Low severity |

### VSCode coupling — detailed inventory (review supplement)

| Category | Severity | Location | Maps to |
|----------|----------|----------|---------|
| Hardcoded `code` CLI in `toolchains.yaml` | High | `toolchains.yaml:38-40` | A1 follow-up |
| Hardcoded `code` CLI in `roo/descriptor.py` | High | `roo/descriptor.py:27-60` | A1 follow-up |
| `~/.vscode/extensions` path probing | High | `host_capabilities.py:15-91` | A1 follow-up |
| `.vscode` directory detection | Medium | `status.py:89`, `host_capabilities.py:46` | A1 follow-up |
| `VsCodeExtension` data type in descriptor model | Medium | `descriptors/base.py:53-56,126` | A1 follow-up |
| `vscode-mode` config field | Medium | `status.py:61,67`, `provider_config.py:42-49` | A1 follow-up |
| `surface: "vscode"` in JSON schema enums | Low | 5 schema files | Not a defect |
| `package_manager == "vscode"` gating | Medium | `registry.py:112`, `reconcile.py:141` | A1 follow-up |
| LSP 3.17 protocol | Low | `lsp_lifecycle.py` | Not a defect |
| Docker test stubs for `code` | Low | `Dockerfile.test-base:41-44` | Test infrastructure |

### Logic bleeding — cross-layer dependency audit (review supplement)

| Foundation file | Runtime import | Risk |
|-----------------|----------------|------|
| `foundation/features/state.py:6` | `runtime.config` | Circular via `runtime.config -> foundation.io` |
| `foundation/features/loader.py:7` | `runtime.config` | Same |
| `foundation/components/registry.py:8-9` | `runtime.config`, `runtime.home` | Same |
| `foundation/components/loader.py:7` | `runtime.config` | Same |
| `foundation/components/dependencies.py:25` | `runtime.config` | Same |
| `foundation/logging/config.py:41,102,116` | `runtime.harness.paths`, `runtime.config` | Same |

**Fix (A8) — Completed 2026-06-21:** expanded to include generic layered config,
home, and package-root helpers so the architecture search is clean: no
`foundation/` module imports `runtime`.

### Copy-pasted patterns — consolidation targets (review supplement)

| Pattern | Instances | Target location | Tracking ID |
|---------|-----------|-----------------|-------------|
| Schema validation `_validate()` | 11 files | `foundation/contracts/schema_registry.py` | C11 (Done) |
| MCP `main()` bootstrap | 10 files | `foundation/mcp/component_server.py` | A18 (Done) |
| MCP `build_server()` manual construction | 4 files | `mcp_server(__name__)` factory | A18 (Done) |
| Raw `yaml.safe_load(path.read_text())` | 15 files | `foundation/io.py` | A8 (Done) |
| `path.parent.mkdir()` before write | 30+ files | `foundation/io.py` | Not a defect |
| State machine implementation | 2 files | `foundation/workflow/state_machine.py` | A21 (Deferred) |
| MCP config format read/write/remove | 5 files | `foundation/mcp/config_adapter.py` | A19 (Closed) |
| `SurfaceFile` duplicates `ComponentFile` | 2 files | Reuse foundation type | A20 (Done) |
| `SurfaceDescriptor` duplicates `ComponentDescriptor` | 2 files | Reuse foundation type | A20 (Done) |

### Patterns that passed review and should be preserved

* `providers/descriptors/feature_mapping.py` is table-driven and has no
  provider-name literals.
* `providers/services/feature_resolution.py` separates activation resolution
  from projection side effects.
* Feature binding descriptors now require explicit `feature-kind`, preventing
  LSP defaults from bleeding into non-LSP bindings.
* Component ID constants in `foundation/components/ids.py` are intentional API
  constants, not a defect by themselves.
