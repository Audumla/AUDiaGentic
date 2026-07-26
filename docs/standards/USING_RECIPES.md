# Using Recipes

How a component/capability provisions itself into a provider (installs code,
writes config, drops guidance). Read this before writing a new recipe class.

## 1. Mental model

A **recipe** is thin registry-facing wiring around the generic lifecycle. Its
job is to *choose* the right existing machinery and feed it domain data — **not**
to reimplement config management.

```
ProvisioningRecipe (foundation) ── lifecycle contract
   probe / install / configure / verify / uninstall / prune
   + default provision()/teardown() orchestration
   + to_result() stamping hook
```

**Hard rule (§10 + the ManagedEntryRecipe lesson):** if an operation already has
a home — MCP entries, instruction blocks, owned config entries, declared
installers — call that home. Do not re-derive it in your recipe body, and never
invent a foundation pattern for a single consumer.

## 2. Pick the mechanism

| You need to… | Use | Layer |
|---|---|---|
| Install/configure/uninstall a capability's **own** artifacts as declared data | **declarative YAML recipe** (`load_recipe_from_yaml` + `execute_recipe_mode`) | foundation `recipe_loader` / `recipe_execution` |
| Run declared install/uninstall steps behind a source gate (programmatically) | `DeclaredStepRecipe` + `InstallManifest` | foundation `recipe_patterns` |
| Report "no automation, a human does X" | `NoAutomationRecipe` | foundation `recipe_patterns` |
| Add/remove an MCP server entry in a **provider** config | `sync_managed_provider_mcp_subset` | providers/services/mcp |
| Add/remove a managed **instruction/rules block** in a provider file | `apply_provider_surfaces` / `SurfaceBlock` | providers/surfaces |
| Reconcile owned named entries in **any** config (with ownership) | `reconcile_fragments` + `FragmentStore` | foundation `toolchains/fragments` |
| Install a **provider's own CLI** via a toolchain | `CliInstallRecipe` (descriptor `cli_install`) | providers/descriptors |
| Write a file your capability **wholly owns** | write it directly (thin) | your component |

If none fit, you likely have genuinely new domain logic — keep it minimal and
local; do not generalize until a second consumer exists (rule of three).

## 3. The lifecycle contract

Implement the six primitives; `provision()`/`teardown()` orchestrate them for
free (probe→install→configure→verify; prune→uninstall→verify-absent). Return a
plain `RecipeResult`; primitives never construct provider result types.

```python
from audiagentic.foundation.toolchains.recipe_contract import (
    ProvisioningRecipe, RecipeResult, RecipeState,
)
```

- **Idempotent skip:** `probe()` returns `RecipeState.VERIFIED` when already done.
- **Gate refusals / manual steps:** put user guidance on `RecipeResult.action_needed`.
- **Step execution:** never build subprocess logic — use `run_steps()` +
  `steps_from_defs()`; guard raw command strings with `safe_command_parts()`.
- **Frozen-safe:** the orchestration uses `dataclasses.replace()`; don't mutate
  results in place.

## 4. Install via declared steps

Steps are the unit of work: **declare them as data, never hand-roll the I/O.**
The step vocabulary (foundation `steps`, selected by `type`):

| type | does | reverts by |
|---|---|---|
| `shell` | run a command (with `platform` overrides, `compensate-command`) | compensate command |
| `download` | fetch remote files to a dir (`base-url` + `files` + `dest-dir`, `optional-files`) | removing what it created |
| `config-set` / `config-remove` | set / remove a nested key in a JSON/TOML/YAML file the capability **owns** (`ConfigPatcher`) | restoring prior value |
| `write-file` | write a wholly-owned file | restoring prior content |
| `managed-block` | apply a managed region in a shared text file | removing the block |
| `managed-mcp` / `managed-hooks` / `managed-plugin` *(providers layer)* | reconcile owned MCP / hook / plugin entries **through the managed family** (ownership-scoped; never raw-writes the provider file) | prune the owned entries |
| `callable` / `sequence` / `conditional` / `select` / `confirm` | control flow + escape hatch | per-step |

Step types are **registry-driven**: each type co-locates its builder and its
JSON-schema fragment (`register_step_type(name, builder, schema=…)`). Foundation
registers the neutral builtins; the providers layer registers the `managed-*`
shielded seams (§6) from `components/providers/services/recipe_steps.py`. Any
component that needs a specialized step registers its own builder + fragment the
same way — there is no hard-coded step-type list in the recipe schema.

**Config-first mandate:** if an install is *fetch files + write config*, express it
as a **declarative YAML recipe** — data, no Python per provider. This is the
preferred path; reach for a Python `DeclaredStepRecipe` only when a source-gate or
programmatic composition genuinely needs it.

```yaml
# config/components/<component>/recipes/<name>.yaml
recipe-id: mycap-codex
recipe-version: "1.0.0"
parameters:
  - {name: URL, required: true}
  - {name: TOKEN, default: "", sensitive: true}
lifecycle:
  install-steps:
    - {type: download, id: fetch, base-url: "https://…", dest-dir: ~/.mycap, files: [a.py]}
  configure-steps:
    - {type: config-set, id: url, path: ~/.mycap/config.json, key-path: [apiUrl], value: "{URL}"}
  uninstall-steps:
    - {type: config-remove, id: url, path: ~/.mycap/config.json, key-path: [apiUrl]}
```

```python
from audiagentic.foundation.toolchains.recipe_execution import execute_recipe_mode
# mode is apply | prune | status | plan; {KEY} params filtered to the recipe's declared set
result = execute_recipe_mode(recipe_path, {"URL": url, "TOKEN": token}, "apply")
```

Validated by `config/recipes/declarative-recipe.schema.json`. Adding a new
provider integration is a YAML drop-in, not new code.

**Programmatic form** — same steps behind a source gate, when Python is warranted:

```python
from audiagentic.foundation.toolchains.recipe_patterns import (
    DeclaredStepRecipe, InstallManifest,
)

installer = DeclaredStepRecipe(
    InstallManifest(
        install_steps=(...),        # tuple[dict]
        uninstall_steps=(...),
        status_command="my-cli --status",   # optional probe
        verified=True,              # gate: refuse steps from an unverified source
        source_label="unconfirmed", # word used in gate messages
        gate_action="verify the source first",
        recipe_id="mycap-<provider>",
    ),
    params={"URL": url, "TOKEN": token},     # {KEY} substitution
    subject="installer",                      # noun in messages
)
result = installer.install(ctx)   # returns plain RecipeResult
```

Your recipe holds this as a field and delegates the reusable primitives to it;
keep only capability-phrased no-ops (e.g. a custom `configure` status) local.

## 5. No-automation guidance

```python
from audiagentic.foundation.toolchains.recipe_patterns import NoAutomationRecipe

delegate = NoAutomationRecipe(
    action_needed="install the X plugin manually",
    skip_status="skipped: no automated X integration",
)
```

`provision()` is a **successful skip** (nothing to do), not a failure.

## 6. Provider config operations — the managed-vs-raw boundary

A recipe **may** orchestrate a whole provider integration and materialize it
through **any** provider capability that can express the feature (MCP entry,
hooks, plugin entry, surfaces, language-server projection, …). That is what
recipes are *for*. The boundary is not "recipe vs. family" — it is
**managed vs. raw**:

- A recipe **calls the provider's managed/shielded layer** to mutate anything
  inside a **provider-owned file** (the harness's own MCP/hooks/settings config).
  That layer is ownership-scoped, format-aware, reload-aware, and multi-caller
  safe. A recipe **never raw-writes** a provider-managed path — no `config-set`,
  `write-file`, or `managed-block` step pointed at a file a provider owns.
- A recipe **may write directly** only to files the capability **wholly owns**
  (not provider-managed) — e.g. Hindsight's `~/.hindsight/*`.
- If materializing a feature needs a managed capability the provider does **not**
  expose, **add that capability** (a new automation family / shielded
  reader-writer-remover on the provider descriptor) or review feasibility — do
  **not** work around the gap by raw-writing the provider's file. Raw content in
  a managed file is the defect; the fix is a managed seam, not a bypass.

Existing managed seams a recipe composes:

**MCP server entry** — the recipe body calls the sync; it does not own the write:

```python
from audiagentic.components.providers.services.mcp import (
    sync_managed_provider_mcp_subset,
)

sync_managed_provider_mcp_subset(
    provider_id, project_root,
    {"ag-mycap": (server_name, mcp_entry)},   # managed_id -> (name, McpServerEntry)
    managed_ids={"ag-mycap"},                  # subset: never touch other owners
)   # to remove: pass {} for the managed_id
```

**Instruction / rules block** — contribute a `SurfaceBlock`; do not hand-roll
`apply_managed_block` into the same file the surfaces system manages (that is a
dual-writer bug — the two managed regions can strip each other).

```python
from audiagentic.components.providers.surfaces.manager import apply_provider_surfaces
# supply your block via the surfaces contribution path; hindsight-style raw
# apply_managed_block into a provider instruction file is prohibited.
```

**Generic owned entries** (non-provider config) — `reconcile_fragments`:

```python
from audiagentic.foundation.toolchains.fragments import FragmentStore, reconcile_fragments
# store = read/write/remove callables; owner_scope isolates your ownership.
```

## 7. Wire into the registry

Provider-scoped recipes subclass `ProviderCapabilityRecipe` and register by
`(provider_id, capability_id, backend_id)`. Provenance (source, `action_needed`)
is stamped **once** at the dispatch boundary via `to_result()` — do not stamp in
every primitive.

```python
class MyCapRecipe(ProviderCapabilityRecipe):
    def __init__(self, ...):
        super().__init__(provider_id=..., capability_id="mycap", ...)
        self._installer = DeclaredStepRecipe(...)      # compose, don't inherit
    def install(self, ctx): return self._installer.install(ctx)
    # to_result() overlay is inherited; keep primitives returning RecipeResult
```

## 8. Worked example — Hindsight (config + generic seams, zero per-provider code)

Hindsight is the reference for the config-first mandate. It splits every
integration into two owners and holds **no** hand-rolled per-provider writer:

- **Provider-owned config** (the MCP entry, Codex hook entries, plugin entry) is
  delegated to the generic provider families via `providers_api`
  (`manage_mcp_entries` / `manage_hook_entries` / `manage_plugin_entry`). Memory
  never formats another harness's config.
- **Hindsight-owned artifacts** (`~/.hindsight/*`: the Codex hook scripts +
  `codex.json`, the Pi host block in `config.json`) are **declarative YAML
  recipes** under `config/components/memory/recipes/`, run through
  `execute_recipe_mode`. `provision.py` holds only a data catalogue
  (`_ARTIFACT_RECIPES = {provider_id: recipe.yaml}`) and a provider-agnostic
  parameter builder — resolution picks the first supported family in fixed order,
  runs the family call, then runs the optional artifact recipe.

Adding a provider is: (1) declare its automation family in the provider
descriptor; (2) if it needs Hindsight-owned side files, drop a YAML recipe in the
catalogue. No `if provider_id == …` branches, no new Python.

Doctrine that got it here:

- **Declared, not hand-coded.** A recipe never reads/writes provider config
  itself (§6) and never re-implements a JSON merge — `config-set`/`config-remove`
  over `ConfigPatcher` do it with rollback and foreign-key preservation.
- **Config over code.** Per-provider facts (URLs, bank ids, host-block shape,
  script lists) live in YAML + descriptors, never in branches.
- **Generic over bespoke.** New primitives (`download`, `config-remove`) are
  added to foundation `steps` as domain-neutral vocabulary — usable by any
  recipe — not as Hindsight-specific helpers (ARCHITECTURE_STANDARDS §1).

## 9. Anti-patterns (do not repeat)

- **Raw-writing a provider-managed file from a recipe.** A recipe orchestrating
  a provider integration is fine and encouraged (§6); the defect is a step that
  writes *unmanaged* content straight into a file a provider owns, bypassing the
  ownership-tracked seam. MCP entries → the MCP sync; instruction blocks →
  surfaces; hooks → the hooks family. If no managed seam exists for what you need,
  add one — do not raw-write (see SL13).
- **A foundation pattern with one consumer.** `ManagedEntryRecipe` was extracted
  for one caller and duplicated the provider MCP machinery — it is being retired
  (SL13). Prefer the existing home over a new abstraction.
- **A config layer on top of the classes it was meant to replace.** If the old
  recipe classes still exist after you add a spec/assembler, it is duplication,
  not simplification (SL15 attempt 1 → SL16 revert). Delete the classes.
- **Per-method provenance stamping.** Return `RecipeResult`; let the boundary
  stamp (SL11).
- **Hand-rolled subprocess/config writes.** Use `run_steps`/`ConfigPatcher`/
  `reconcile_fragments`, never raw `subprocess`/file writes in a recipe — and for
  provider-owned files, go through the managed seam, not `ConfigPatcher` directly
  (§6).

## 10. Reference

- Declarative YAML recipe: loader `foundation/toolchains/recipe_loader.py`,
  materializer `recipe_materializer.py`, runner `recipe_execution.py`
  (`execute_recipe_mode`); schema `config/recipes/declarative-recipe.schema.json`
- Step vocabulary + factory: `foundation/steps/` (`factory.py` registry,
  `structured.py` config/write/download steps, `shell.py`)
- Contract + orchestration: `foundation/toolchains/recipe_contract.py`
- Reusable patterns: `foundation/toolchains/recipe_patterns.py`
- Ownership reconciler: `foundation/toolchains/fragments.py`
- Config mutation primitive: `foundation/toolchains/config/config_patcher.py`
- Provider MCP machinery: `components/providers/services/mcp.py`
- Provider surfaces: `components/providers/surfaces/`
- Worked example (config-first, zero per-provider code):
  `components/memory/hindsight/provision.py` +
  `config/components/memory/recipes/`
- Doctrine: `ARCHITECTURE_STANDARDS.md` §1 (layer boundaries), §10 (no
  speculative abstractions / duplicate paths).
