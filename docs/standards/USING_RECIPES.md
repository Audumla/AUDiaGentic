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
| Run declared install/uninstall steps behind a source gate | `DeclaredStepRecipe` + `InstallManifest` | foundation `recipe_patterns` |
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

The canonical "install code" path. Steps are provision-step dicts
(shell/config-set/write-file/managed-block) run with compensating rollback.

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

## 6. Provider config operations — use the provider machinery

Do **not** write a recipe that reads/writes provider config files itself. These
are ownership-tracked and reload-aware already.

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

## 8. Anti-patterns (do not repeat)

- **Reimplementing provider config management in a recipe.** MCP entries → the
  MCP sync; instruction blocks → surfaces. A recipe that reads/writes those
  files itself is duplicate machinery (see SL13).
- **A foundation pattern with one consumer.** `ManagedEntryRecipe` was extracted
  for one caller and duplicated the provider MCP machinery — it is being retired
  (SL13). Prefer the existing home over a new abstraction.
- **Per-method provenance stamping.** Return `RecipeResult`; let the boundary
  stamp (SL11).
- **Hand-rolled subprocess/config writes.** Use `run_steps`/`ConfigPatcher`/
  `reconcile_fragments`, never raw `subprocess`/file writes in a recipe.

## 9. Reference

- Contract + orchestration: `foundation/toolchains/recipe_contract.py`
- Reusable patterns: `foundation/toolchains/recipe_patterns.py`
- Ownership reconciler: `foundation/toolchains/fragments.py`
- Provider MCP machinery: `components/providers/services/mcp.py`
- Provider surfaces: `components/providers/surfaces/`
- Worked example (wiring, not to copy verbatim): `components/memory/hindsight/`
- Doctrine: `ARCHITECTURE_STANDARDS.md` §1 (layer boundaries), §10 (no
  speculative abstractions / duplicate paths).
