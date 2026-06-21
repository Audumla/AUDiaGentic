# Multi-Layered Component / Implementation / Feature / Option Plan

> **Scope.** This defines a *reusable* component pattern for AUDiaGentic, not an
> LSP-only design. `coding-lsp` is the **first** implementation of the pattern
> and the proving ground; once stable, the same foundation is reused by other
> optional components. Keep the foundation generic and component-agnostic — push
> all LSP-specific facts into `coding-lsp` descriptors, never into the
> foundation layer.
>
> **Staged cutover doctrine (governs execution).** This is still a replacement
> of the old layering, but execution is allowed to use a temporary bridge when a
> component has existing runtime files or tests that would make a single-shot
> deletion risky. The bridge must be named in this plan, have a clear owner, and
> have an explicit decommission step. For `coding-lsp`, that bridge is
> `.coding-lsp/lsp.json`: feature state is now user intent, while `lsp.json`
> remains only as generated cache/projection artifact. Runtime session and
> provider projection paths resolve from feature state and bindings.

## Implementation Status — 2026-06-21

Stages 0, 1, and 2 are complete. Stage 3 is partly landed: provider
enablement uses foundation feature state, provider capabilities as
implementation-scoped features are proven, and the implementation-scoped feature
layer exists. M10 (provider surface bridge) and C2 (Docker provider-LSP e2e
validation, 25 passed) are now done. Remaining: cross-component architecture
cleanup for Stage 5 (A-series open items) and the Stage 4 flat-component
regression.

**Completed items archive:** see `multilayer-component-plan-completed.md`.

### Open Items

* **A14 — done for shared/public seams.** Feature/component/dependency/LSP
  descriptor loaders, workflow state/action/propagation helpers, path/package
  lookup, provider CLI workflow guard, and shared rig binary updater failures now
  use `AudiaGenticError`. Remaining raw built-in exceptions are classified as
  validator internals or adapter-local parser/renderer validation.
* **A25 — done.** `cli_io` module with `print_json`, `print_message`, `print_error`
   unifies CLI/harness output. 80+ raw `print()` sites converted across CLI
   entrypoints, harness, update, rig, contracts, and providers.
* **A26 — done.** Shared-library `SystemExit`/`sys.exit()` sites were converted
  to canonical `AudiaGenticError`. Remaining hits are intentional CLI/MCP
  entrypoint exits or update handoff exits.
* **A21** — state machine unification (deferred).
* **A1 follow-up** — generic host capabilities (Stage 7).
* **C2 Docker e2e — done 2026-06-21.** `tests/integration/coding_lsp/test_provider_lsp_e2e.py`
  ran green in the Docker harness: **25 passed in 24.78s** (default python+typescript
  servers; rust/cpp gated behind `AUDIAGENTIC_LSP_E2E_ALL=1`). The "stat deadlock"
  was the Windows bind mount (`-v $PWD:/app`), not the test/code — baking the
  source into the image with `COPY` instead of bind-mounting sidesteps it:
  `docker build -t audiagentic-provider-lsp-e2e-baked -f - . <<'EOF'` /
  `FROM audiagentic-provider-lsp-e2e:latest` / `COPY . /app` / `EOF`, then
  `docker run --rm audiagentic-provider-lsp-e2e-baked` (no `-v`).
* **E3 — done.** Release finalization emits a synchronous ledger archive event;
  ledger owns sync/archive handling.
* **E4 — done.** Component CLI no longer owns harness refresh/reload side
  effects; lifecycle mutations route through the project component API.
* **M10 — done.** The `type: provider` surface bridge was vestigial (zero
  importers, loaded by nothing); the module and 7 YAMLs were deleted and
  `FileBearingDescriptor` collapsed back into `ComponentDescriptor`.
* **A30 (optional)** — VS Code `.vscode/extensions.json` recommendations. When a
  provider declares `host_capabilities` for the `vscode` host, generate
  `.vscode/extensions.json` so VS Code surfaces "Install Recommended Extensions"
  automatically. Read `package.json` from installed extensions for version/metadata
  instead of ID-only filesystem probe.
* **Stage 4** — flat-component regression.
* **Stage 5** — foundation decommission & unification.

---

## Concise Completion Execution Plan

**Standards enforcement.** `docs/ARCHITECTURE_STANDARDS.md` is the authoritative
list of non-negotiable rules. Every item below must satisfy those standards on
exit.

**Completed items:** see `multilayer-component-plan-completed.md`.

1. **Reconcile plan + verification baseline.**
   Remove stale "open" notes that contradict completed work, keep `lsp.json`
   documented only as generated cache, and run/record the missing Docker
   provider-LSP e2e validation for C2 with a realistic timeout. No new
   architecture work depends on this, but it prevents false blockers.

2. **Fix foundation layer inversions + unify error handling.**
   **A14 done for shared/public seams:** feature/component/dependency/LSP
   descriptor loaders, workflow state/action/propagation helpers, path/package
   lookup, provider CLI workflow guard, and shared rig binary updater failures
   now use `AudiaGenticError`. Remaining raw built-in exceptions are validator
   internals or adapter-local parser/renderer validation. All other items in
   this step (A8, C11, A13, A15) are done.
   See `multilayer-component-plan-completed.md` for detail.
   Gate: foundation feature/component/contract tests plus runtime config compatibility.

3. **Close provider capability modeling.**
   **M10 done 2026-06-21.** The `type: provider` surface bridge was vestigial,
   not converted: `surfaces/descriptors.py` (`SurfaceDescriptor`,
   `load_all_surfaces`, `get_surface_descriptor`, …) had zero importers, and the
   7 `type: provider` YAMLs (`claude/cline/codex/copilot/gemini/opencode/qwen`)
   were loaded by nothing — the foundation loader's nested scan only handles
   `feature`/`implementation`/`binding` and silently skips `type: provider`. All
   were deleted; provider capabilities (`mcp`, language-server support, surfaces,
   skills) are derived from `ProviderDescriptor`. Deleting `SurfaceDescriptor`
   left `FileBearingDescriptor` (the A20 tier) with a single subclass, so it was
   collapsed back into a flat `ComponentDescriptor`. A4 and A5 are done.
   Gate: foundation/providers/coding-lsp unit suites green; 8 components still
   load; Ruff clean.
   Gate: provider unit/integration suites and parity output.

4. **Shrink deterministic runtime rendering.**
   **Completed C8/A16/A17 2026-06-21:** baseline sync no longer contains
   component-specific virtual renderers or contribution-ID branches. Unstable
   agent-jobs prompt syntax/catalog assets were removed from baseline generation
   and are derived at runtime with optional project overrides. Stable project
   config, release workflow, and ledger/release skill assets are ordinary source
   files copied by the existing baseline mechanism. No renderer registry,
   callback layer, or event workaround was added.
   Gate: baseline sync tests plus component lifecycle tests.

5. **Use events for cross-component reactions only.**
   **Completed E3 2026-06-21:** release finalization publishes a synchronous
   ledger archive request event, and ledger owns sync/archive/idempotent handling.
   **Completed E4 2026-06-21:** component CLI now routes lifecycle mutations
   through the project component API, so harness refresh/reload side effects live
   in one project/lifecycle path instead of duplicated command code. Direct user
   command dispatch remains direct; no extra event layer was added.
   Gate: release, ledger, launcher/component lifecycle tests.

6. **Finish LSP projection/catalog unification.**
   **Completed A6/C3 (2026-06-21):** generic MCP projection facts now live in
   implementation descriptor metadata (`projection.generic-mcp`) for `ag-lsp`
   and `agent-lsp`; `language_servers_sync.py` derives managed IDs and entries
   from descriptors. **Folded 2026-06-21:** `language_registry.py` is now sourced
   from the registered feature catalog. The direct YAML scan/fallback path is
   deleted; `_ensure_loaded` registers the component catalog when needed and
   adapts coding-lsp `language` `FeatureDescriptor`s into `LanguageSpec`s. The
   feature catalog is authoritative, including options schema. `LanguageSpec`
   stays in `coding_lsp` by design — `server.command`/`file-extensions`/
   `settings`/probes are LSP-specific and must not move onto the foundation
   `FeatureDescriptor`. **Import-time
   coupling removed 2026-06-21:** no module computes language config at import
   anymore — the dead `_LSP_PROBES`/`_LSP_DEP_LABELS`/`LSP_DEPENDENCY_IDS`
   constants in `coding_lsp_bootstrap.py` were deleted (unused), and
   `lsp_config_api._LSP_PROBES` became a lazy `_lsp_probes()` function so the
   first catalog read happens post-registration. Keep `lsp.json` as cache only.
   Gate: full coding-lsp unit suite plus provider-LSP projection tests green.

7. **Remove central capability edit points.**
   **Done.** A1 follow-up: rename/model VS Code extension support as generic
   host capabilities without building a broad multi-editor framework before a
   second host exists. A9, A10, M11 done.
   See `multilayer-component-plan-completed.md` for detail.

8. **Consolidate duplicated patterns.**
   **A18, A19, A20 done.** A21 (state machine unification) remains deferred.
   See `multilayer-component-plan-completed.md` for detail.
   Gate: MCP server tests, provider adapter tests, agent-jobs state tests.

9. **Logging infrastructure cleanup.**
   **A22, A23, A24, A26 done.** Shared foundation, harness, and runtime rig
   library helpers no longer raise `SystemExit`; remaining exits are CLI/MCP
    entrypoint or update handoff boundaries. **A25 done:** `cli_io` module with
    `print_json`, `print_message`, `print_error` unifies CLI/harness output.
   See `multilayer-component-plan-completed.md` for detail.
   Gate: logging tests, MCP tool call tests, provider adapter tests.

10. **Stage 4/5 final decommission.**
    Run flat-component regression for ledger/release/source-control. Delete
    superseded loaders, compatibility shims, dead bridge code, and tests that
    target deleted helpers. Keep direct file I/O, adapter-local policy, and
    adapter-local renderer IDs where they remain clearer and domain-local.
    Gate: full suite, Ruff, and architecture searches: no `foundation -> components`
    imports; no runtime imports from optional component internals except through
    contribution/event APIs; no central hardcoded provider/LSP implementation
    lists; no parallel exception hierarchies; no silent `except: pass` outside
    teardown.

---

## 1. Core Design

The pattern has five layers:

* **Component** — top-level lifecycle unit (e.g. `coding-lsp`, `providers`).
* **Implementation** — a **global**, first-class selectable unit within a
  component. "Global" means selecting/enabling it is a component-level decision,
  not a per-sink one; its effect is pushed out wherever the component projects.
  A component declares whether its implementations are **exclusive** (at most one
  active — LSP) or **multi-active** (many active at once — providers). Exclusivity
  is per-component policy, *not* a rule of the pattern.
* **Feature** — a capability enabled under an implementation (or shared across a
  component's implementations). A feature may be **component-shared** (available
  to every implementation — e.g. LSP languages) or **implementation-scoped**
  (owned by one implementation — e.g. a provider's surfaces/skills). Features may
  themselves be complex (own sub-options, own dependencies).
* **Binding** — derived rule describing how an implementation and a feature work
  together. Activated automatically, not enabled directly.
* **Option** — typed, schema-validated setting owned by any of the above layers.

> **Implementation is a first-class layer, not a feature-kind.** Earlier drafts
> encoded implementation as `kind: implementation` under the feature model. That
> only holds for the LSP case (shared features, one active). The provider
> component breaks it: providers are implementations, many are active at once,
> and each owns *different* features. So implementation gets its own descriptor
> type and can own features. See §14 for the two-component mapping that drives
> this.

### Component

A **component** is the top-level lifecycle unit.

Example:

```text
coding-lsp
```

The component owns high-level lifecycle operations such as install, configure, enable, disable, status, and projection sync.

### Feature

A **feature** is a selectable capability inside a component.

For `coding-lsp`, implementation ids and feature kinds include:

```text
implementation.ag-lsp
implementation.agent-lsp

language.python
language.typescript
language.rust
```

For `coding-lsp`, implementations are exclusive (one active). Language features
are independently enabled or disabled and are shared across implementations.

**Feature scope.** For `coding-lsp`, language features are *component-shared*:
the same enabled languages apply regardless of which implementation is active,
which is why switching implementation must not touch language enable flags.
Other components declare *implementation-scoped* features instead (the provider
component does — each provider owns its own surfaces/skills). The descriptor
model must express both — a feature carries either a component `parent` (shared)
or an `implementation` scope (owned by one implementation). LSP exercises only
the shared case in the first cut; the provider component exercises the scoped,
multi-active case (see §14).

### Binding

A **binding** is a rule that describes how two or more features work together.

Examples:

```text
ag-lsp + python
agent-lsp + python
ag-lsp + rust
agent-lsp + rust
```

Bindings are not usually enabled directly. They become active when their required features are active.

For example:

```text
implementation = agent-lsp
language.python = enabled
```

activates:

```text
binding.agent-lsp.python
```

### Option

An **option** is a typed setting owned by a component, feature, or binding.

Examples:

```text
coding-lsp.max-diagnostics

implementation.agent-lsp.warm-runtime
implementation.agent-lsp.output-format

language.python.type-checking-mode

binding.agent-lsp.python.server-profile
```

Options should have schemas, defaults, validation, and a clear merge order.

---

## 2. State Model

Keep user intent separate from implementation mechanics.

> **Active-set, not a selected scalar.** The example below uses
> `selected.implementation: agent-lsp` because LSP is exclusive. That scalar is a
> *projection of policy*, not the canonical state. The canonical activation state
> is the per-implementation `enabled` flag (an active-**set**). For an exclusive
> component the lifecycle enforces "at most one enabled"; for a multi-active
> component (providers) many are enabled and there is no `selected` field at all.
> Derive `selected` for exclusive components; never store it as the source of
> truth. See §15.

Example stored state (exclusive component — `coding-lsp`):

```yaml
coding-lsp:
  enabled: true

  # No `selected` field is stored. Activation is the per-implementation `enabled`
  # flags below (the active-set). For an exclusive component the lifecycle keeps
  # at most one enabled; `selected` is *derived* for status output only.

  options:
    max-diagnostics: 500

  implementations:
    ag-lsp:
      enabled: false
      options:
        session-timeout-seconds: 900

    agent-lsp:
      enabled: true
      options:
        warm-runtime: true
        output-format: gcformat

  features:
    languages:
      python:
        enabled: true
        options:
          type-checking-mode: basic

      rust:
        enabled: true
        options: {}
```

Important behaviour:

* Shared features (LSP languages) are enabled once and persist across
  implementation changes.
* Changing the active implementation does not disable shared features.
* Binding activation is derived from the active implementation(s) and enabled
  features — never stored.
* `selected` (exclusive components only) is derived from the active-set for
  display; it is not source-of-truth.
* Generated provider files are projections, not source-of-truth state.

Example:

```text
Before:
  implementation = ag-lsp
  languages = python, rust

After switching implementation:
  implementation = agent-lsp
  languages = python, rust
```

The user's language intent remains unchanged.

---

## 3. Descriptor Model

Three descriptor types: `component`, `implementation`, `feature`, plus
`binding`. Implementation is **first-class** (`type: implementation`), not a
feature kind. A component declares activation cardinality once (see Component
Descriptor); individual implementations do not carry `exclusive-group`.

### Component Descriptor

```yaml
type: component
id: coding-lsp
# exclusive: at most one implementation active. multi: many active (providers).
implementation-cardinality: exclusive
```

### Implementation Descriptor

```yaml
type: implementation
parent: coding-lsp
id: agent-lsp

dependencies:
  agent-lsp:
    probe: binary:agent-lsp
    via:
      winget: BlackwellSystems.agent-lsp
    platform-fallback:
      windows:
        - powershell
        - -File
        - install.ps1

options-schema:
  warm-runtime:
    type: bool
    default: true

  output-format:
    type: enum
    values:
      - json
      - gcformat
    default: gcformat
```

### Feature Descriptor

A feature is component-shared (`parent: <component>`, applies to every
implementation — the LSP language case) or implementation-scoped
(`implementation: <id>`, owned by one — the provider-surface case). LSP
languages are shared:

```yaml
type: feature
parent: coding-lsp        # shared across implementations
kind: language            # component-defined feature kind (free-form label)
id: python

options-schema:
  type-checking-mode:
    type: enum
    values:
      - off
      - basic
      - strict
    default: basic

dependencies:
  pyright:
    probe: binary:pyright-langserver
    toolchain: uv
    package: pyright
```

### Binding Descriptor

Projection is a **registered callable**, referenced by a registry key — not a
dotted import path (see §14 Q4). Each binding writer/remover is registered in
the component's binding registry under `(implementation, feature)`.

```yaml
type: binding
parent: coding-lsp
implementation: agent-lsp
feature: python

uses-dependencies:
  - feature.language.python.pyright

projection:
  writer-key: agent-lsp.python     # resolved in the binding registry to a callable

options-schema:
  server-profile:
    type: enum
    values:
      - pyright
      - basedpyright
    default: pyright
```

---

## 4. Resolution Model

### Effective Config Merge Order

```text
component descriptor defaults
+ component state options
+ implementation descriptor defaults
+ implementation state options
+ feature descriptor defaults
+ feature state options
+ binding descriptor defaults
+ binding state options
```

### Dependency Closure

```text
active implementation dependencies
+ enabled feature dependencies
+ active binding dependencies
```

### Projection Closure

For **shared** features:

```text
active implementation(s) x enabled shared features
```

For **implementation-scoped** features there is no cross-product: the feature
already belongs to one implementation, so the binding set is just that
implementation's own (implementation, scoped-feature) pairs.

---

## 5. Implementation Switching

This sequence is the *exclusive* (single-active) case. A multi-active component
has no "switch" — enable/disable each implementation independently.

```text
1. Load current feature state.
2. Resolve target implementation.
3. Resolve enabled shared features.
4. Resolve active bindings.
5. Build dependency closure.
6. Probe/install missing dependencies.
7. Remove old implementation-managed projection entries.
8. Write new implementation projection entries.
9. Persist the active implementation set (exclusive: deselect the prior one).
10. Leave shared-feature enabled flags unchanged.
```

Failure behaviour:

```text
If dependency install or projection fails:
  - do not mutate the active implementation set
  - preserve existing feature state
  - preserve working old projection where possible
  - report the failure clearly
```

---

## 6. Foundation Implementation Plan

```text
src/audiagentic/foundation/components_ext/base.py
src/audiagentic/foundation/components_ext/loader.py
src/audiagentic/foundation/components_ext/registry.py
src/audiagentic/foundation/components_ext/implementation.py
src/audiagentic/foundation/components_ext/feature.py
src/audiagentic/foundation/components_ext/binding.py
src/audiagentic/foundation/components_ext/state.py
src/audiagentic/foundation/components_ext/options.py
src/audiagentic/foundation/components_ext/resolver.py
src/audiagentic/foundation/components_ext/lifecycle.py
```

### Descriptor Models

```text
ComponentDescriptor, ImplementationDescriptor, FeatureDescriptor,
BindingDescriptor, OptionSchema, DependencyRef, ResolvedConfig,
ResolvedBindingConfig, ResolvedState
```

### YAML Loader

```text
type: component | implementation | feature | binding
parent, id, implementation-cardinality, dependencies, uses-dependencies,
options-schema, projection.writer-key
```

### Registry

```text
get_component(component_id)
get_implementations(component_id)
get_implementation(component_id, implementation_id)
get_features(component_id, kind=None)
get_implementation_features(component_id, implementation_id)
get_feature(component_id, kind, feature_id)
get_bindings(component_id)
get_binding(component_id, implementation_id, feature_id)
get_binding_writer(component_id, writer_key)
```

### Feature State Store

```text
.audiagentic/config/runtime/features.yaml
```

### Option Resolver

```text
- apply defaults
- validate bool/string/int/enum/list/object types
- validate enum values
- validate min/max where relevant
- reject unknown options unless explicitly allowed
- return merged effective config
```

### Lifecycle Service

```text
list_features, get_feature_status, enable_feature, disable_feature,
set_feature_option, reset_feature_option,
enable_implementation, disable_implementation,
select_exclusive_implementation, resolve_active_dependencies,
sync_feature_projection
```

---

## 7. Dependency Engine Integration

Reuse the existing dependency engine. Feed feature and binding dependency maps
into `build_dependency_workflow`. Add `resolve_active_dependencies(parent_id,
project_root)`.

---

## 8. LSP Descriptor Conversion

Status: descriptor conversion is done for shipped LSP languages and
implementations. `language_registry.py` is now only the coding-lsp adapter from
registered `FeatureDescriptor`s to LSP runtime `LanguageSpec`s; it no longer
scans YAML directly or supports `type: language`.

```text
config/components/optional/coding-lsp.yaml
config/components/optional/coding-lsp/ag-lsp.yaml
config/components/optional/coding-lsp/agent-lsp.yaml
config/components/optional/coding-lsp/python.yaml
config/components/optional/coding-lsp/typescript.yaml
config/components/optional/coding-lsp/rust.yaml
config/components/optional/coding-lsp/cpp.yaml
config/components/optional/coding-lsp/bindings/ag-lsp.python.yaml
config/components/optional/coding-lsp/bindings/agent-lsp.python.yaml
...
```

---

## 9. LSP API (clean replacement)

Current API surface:

```text
lsp_config_status, lsp_list_implementations, lsp_select_implementation,
lsp_add_language, lsp_remove_language, lsp_list_languages,
lsp_set_language_option, lsp_reset_language_option,
lsp_install_dependencies, lsp_list_missing
```

Open decommission decision:

* keep `lsp_add_language` / `lsp_remove_language` as canonical names, or rename
  to `lsp_enable_language` / `lsp_disable_language`

---

## 10. LSP Sync Rework

After Stage 2 decommission, projection is computed from resolved feature state:

```text
active implementation + enabled features + active bindings => generated projection
```

Projection rules: deterministic, idempotent, prune managed, preserve unmanaged.

---

## 11. Migration Compatibility

Status: `features.yaml` is the feature intent store, `lsp.json` remains the
runtime server projection. One-time importer dropped for greenfield/template.

---

## 12. Tests

Minimum tests (keep-green / rewrite / add per stage).

---

## 13. Coding-LSP Cut (Stage 2 detail)

Re-implement `ag-lsp` on the new foundation. Add `agent-lsp` as the second
implementation descriptor. Test the full switch path.

---

## 14. Review Notes & Open Questions

### Two-component mapping (the design driver)

| Pattern layer | `coding-lsp` | `providers` |
| --- | --- | --- |
| Component | `coding-lsp` | `providers` |
| Implementation | `ag-lsp`, `agent-lsp` — **exclusive** | `claude`, `codex`, `cline`, … — **multi-active** |
| Feature | language (python, rust…) — **shared** | surfaces / skills / lsp-support — **impl-scoped** |
| Binding | implementation × language | provider × feature |
| Option | per layer | per layer |

### Q1 — RESOLVED: implementation is a global, first-class layer

### Q2 — RESOLVED: implementation projection is global; sinks react on their own

### Q3 — Projection mechanism: reuse the existing managed-id machinery

### Q4 — Projection hooks: callables, not dotted strings

### Q5 — Options resolver: design now, implement lazily

### Q6 — State store: one location, no compatibility loader

### Confirmed-accurate plan claims

* Reusing `build_dependency_workflow` / `build_dependency_probes` — accurate
* The new LSP API (§9) calls the feature/implementation layer directly

### Sequencing

Authoritative staged order: §17 stage/capability/test matrix.

---

## 15. Second Component Migration — `providers`

Migrating `providers` is the **co-design partner**. Validates multi-active
implementations, implementation-scoped features, and per-implementation projection.

**Where provider state actually lives.** The provider *runtime* descriptor is a
Python `ProviderDescriptor` dataclass registered via `register()` on adapter
import. The `type: provider` YAML is **surface/file config**, not the runtime
descriptor.

Validation ladder:

1. Schema load/resolve only — express Python descriptors against foundation schema
2. Parity diff (throwaway verification)
3. Cutover — switch runtime, delete old path

Migration guardrails (greenfield):

* Parity diff verifies output equivalence before cutover
* Express per-provider capabilities as implementation-scoped features
* Two components must share one foundation registry/loader/resolver

---

## 16. Component Inventory & Pattern Mapping

### What exists today

| Component | Sub-descriptor today | New mapping |
| --- | --- | --- |
| `coding-lsp` | feature-shaped language YAML + `lsp.json` bridge | implementation + **shared** feature |
| `providers` | `type: provider` YAML + Python `ProviderDescriptor` | implementation + **impl-scoped** features |
| `agent-jobs` | `type: action` YAML | **features only** |
| `ledger` | none (flat) | no sub-layer |
| `release` | none (flat) | no sub-layer |
| `source-control` | none (flat) | no sub-layer |

### Per-component verdict

* **`agent-jobs` — features only (Stage 1, done).**
* **`coding-lsp` — full migration (Stage 2, done; cache bridge remains).**
* **`providers` — full migration (Stage 3, partly done).** Pending: M10 legacy
  surface metadata decision and final Stage 5 cleanup.
* **`ledger` / `release` / `source-control` — no sub-layer (Stage 4).**

> **The foundation must support three layer configurations — not assume all
> four layers are present.**
> 1. implementations + shared features + bindings — `coding-lsp`
> 2. implementations + impl-scoped features + bindings — `providers`
> 3. shared features only, no implementations, no bindings — `agent-jobs`

### Shared integration points

1. Component loader/registry
2. MCP propagation
3. Surfaces / contributions
4. Dependency engine
5. Lifecycle/status hooks

---

## 17. Staged Implementation Roadmap

### Stage / capability / test matrix

| Stage | Component | Foundation capability added | Deletes | Test groups (action) |
| --- | --- | --- | --- | --- |
| 0 | — | component + feature, state, options, resolver | nothing | **DONE** |
| 1 | `agent-jobs` | first feature-only consumer | `type: action` sub-loader | **DONE** |
| 2 | `coding-lsp` | implementation + binding + registry, exclusive cardinality, dep closure | partial: `type: language` gone; bridge remains | **PARTIAL** — decommission/import tests pending |
| 3 | `providers` | `multi` cardinality, impl-scoped features, active-set lifecycle | provider sync/registration activation path | **IN PROGRESS** — capability modeling/parity/cutover pending |
| 4 | `ledger`/`release`/`source-control` | none (regression) | nothing (unless forced) | KG (**untouched**) |
| 5 | — | unify onto one loader/registry/resolver | all §18 dead code | full suite (KG); delete tests of removed helpers |

**Stages 0–2 detail:** see `multilayer-component-plan-completed.md`.
**Remaining work (Stage 2 residual → Stage 5):** see the dependency-ordered
[Completion Execution Sequence](#completion-execution-sequence-remaining-work) (S1–S5)
near the top of this plan.

### Stage 3 — Foundation +multi-active +impl-scoped; `providers`

Adds `multi` cardinality and implementation-scoped features. `providers` is the
consumer and the multi-active stress test (§15).

**Status after current implementation:**

* `providers.yaml` declares `implementation-cardinality: multi`
* Foundation lifecycle has explicit coverage for multi-active
* Provider enable/disable writes mirror into `features.yaml`
* Provider activation routed through foundation lifecycle helpers
* Provider status and reconcile resolve `enabled` through feature state
* Impl-scoped feature layer landed (registry, state, lifecycle)
* Capability → impl-scoped feature derivation landed
* Impl-scoped resolution landed
* MCP projection unified onto the resolver (landed, enabled-aware)
* Surfaces + skills projection unified onto the resolver (landed, enabled-aware)
* Language-server projection unified onto the resolver (landed, enabled-aware)
* Enabled-aware contract verification landed

**Stage 3 residual before exit:**

* **M10 temporary surface metadata bridge.** `providers.yaml` remains the rich
  per-provider runtime/options store. Old `type: provider` surface YAML may
  remain only as a temporary bridge; Stage 5 exit must delete it or
  convert/derive it into impl-scoped surface feature data.

**Completed findings:** see `multilayer-component-plan-completed.md`.

### Stage 4 — Flat components (`ledger`, `release`, `source-control`)

No feature migration — these have no sub-layer.

* **Touch only if forced:** if an earlier stage changed a shared signature,
  apply the matching config/code update; otherwise leave them.
* **Tests:** *keep-green* — `tests/unit/release/`, `tests/integration/release/`,
  `tests/e2e/release/`, `tests/unit/source_control/`, the ledger test, and the
  `component`-named lifecycle tests.
* **Exit:** flat-component + lifecycle suites green with no edits.

### Stage 5 — Foundation decommission & unification

* Remove every dead per-component sub-loader and helper (see §18).
* Collapse the three old sub-descriptor `type`s onto the one new loader path.
* Confirm surfaces, MCP propagation, and the dependency engine have a single code
  path shared by all migrated components.
* **Tests:** *keep-green* — full suite. *rewrite/delete* — remove tests of deleted helpers.
* **Exit:** no module (or test) imports a deleted helper; one loader, one
  registry, one resolver across the codebase; full suite green.

---

## 18. Foundation Decommission Checklist

Concrete dead code to delete once its replacement lands:

* `coding_lsp/language_registry.py` direct YAML catalog/fallback — **done.**
  Remaining module is the coding-lsp runtime adapter for LSP-specific language
  facts.
* `coding_lsp/lsp_config_api.py` activation/read-write-of-`lsp.json` paths —
  **reclassified.** Remaining `lsp.json` reads/writes maintain generated cache.
* `coding_lsp/language_servers_sync.py` direct `lsp.json → providers` logic —
  **done.**
* `type: language` discriminator + flat `glob("*.yaml")` language load — **done.**
* Provider sync/registration **activation** path (Stage 3) — adapter callables
  survive as binding writers; the activation glue does not.
* `type: action` bespoke sub-loader in agent-jobs (Stage 1).
* Any `_configured_language_ids`-style "read sub-state from the projection file"
  helper across components — activation reads only from `features.yaml`.

> **Process note.** Per project doctrine, record a ledger change event
> (`record_change_event`) after each stage's substantive work, and do not edit
> generated release artifacts directly. Stage cutovers that delete public tool
> surfaces are `change-class` significant — flag them in the ledger.
