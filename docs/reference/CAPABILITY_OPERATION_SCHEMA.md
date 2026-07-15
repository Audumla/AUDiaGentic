# Provider API contract

**Authority:** MA16. This document is the implementation contract for
`audiagentic.components.providers.providers_api`.

## API categories

Every public entry belongs to exactly one category.

| Category | Purpose | Durable mutation | Operation mode |
|---|---|---|---|
| Query | Observe state | None |
| Resource command | Manage AUDiaGentic-owned desired state or cache | AUDiaGentic resource only | None |
| Automation family | Change external provider state or owned contributions inside provider files | Provider/tool state | Supported subset of `plan`, `apply`, `prune`, `status` |
| Agent execution | Run an explicitly composed provider execution adapter | Execution effects only | None |

Provider-specific code does not make a call automation: mutation ownership does.
Resource CRUD and catalog refresh do not use recipe modes. Agent execution is
not an automation family. No universal gateway joins these categories.

## Frozen current export classification

`providers_mcp.py` is the sole current production caller of these public
exports. Tests are validation callers.

| Current export | Category and target | Owner |
|---|---|---|
| `list_providers` | Query; keep | MA31 |
| `get_provider_status` | Query; keep | MA31 |
| `list_provider_descriptors` | Query; keep | MA31 |
| `describe_provider` | Query; keep | MA31 |
| `model_source_list` | Query of desired-state resource; keep | MA31 |
| `list_provider_models` | Catalog query; remove `refresh` flag | MA31 |
| `refresh_provider_catalog` | Catalog resource command; cache write only | MA31 |
| `refresh_all_catalogs` | Batch catalog resource command | MA31 |
| `model_source_add` | Desired-state resource create only | MO02 |
| `model_source_update` | Desired-state resource update only | MO02 |
| `model_source_remove` | Desired-state resource delete, not `prune` | MO02 |
| `model_source_set_enabled` | Desired-state resource update only | MO02 |
| `sync_provider_models` | Replace with model-projection family modes | MO02 |
| `list_provider_models_config` | Fold into model-projection `status` | MO02 |
| `reload_provider_models` | Delete; private model-projection `apply` mechanic | MO02 |
| `install_provider` | Replace with CLI `apply` | MA12 |
| `repair_provider` | Replace with CLI `apply`; recipe selects repair | MA12 |
| `uninstall_provider` | Replace with CLI `prune` | MA12 |
| `apply_provider_surfaces` | Replace with surface `apply` | MA21 |
| `prune_provider_surfaces` | Replace with surface `prune` | MA21 |
| `reconcile_provider` | Delete; explicit family composition | MA22 |
| `reconcile_all_providers` | Delete; explicit iteration/composition | MA22 |

Model-source CRUD persists desired state only. It has no automation mode,
`apply`, or `dry_run` flag. Callers explicitly invoke model projection when
provider state must change. `list_provider_models` is query-only; refresh uses
the explicit catalog resource commands.

## Universal internal recipe schema

Every automation implementation conforms to one provider-owned declarative
`RecipeDefinition` schema. Its common envelope identifies the recipe, provider,
open family id, supported modes, family payload/result contracts, recipe
version, and whether opaque ownership scope is required.

This is an internal schema, not a public request or result. Family payloads and
results remain distinct. It contains no requester identity, provider path,
command, serializer, handler dotpath, or closed family taxonomy. Queries,
resource commands, and agent execution cannot register recipes.

Schema validation describes an implementation; it does not enable one. Only an
explicit provider+family code registration enables automation. Duplicate
registration fails instead of replacing an existing binding.

The frozen definition envelope is:

| Field | Meaning |
|---|---|
| `recipe-id` | Diagnostic identity for the implementation definition. |
| `provider-id` | Provider owning the implementation. |
| `family-id` | Open automation-family identifier registered by composition. |
| `supported-modes` | Supported subset of `plan`, `apply`, `prune`, `status`. |
| `payload-contract` | Reference to the family-specific input contract. |
| `result-contract` | Reference to the family-specific result contract. |
| `recipe-version` | Definition version. |
| `ownership-scope-required` | Whether calls require opaque ownership scope. |
| `provenance-ref` | Optional non-authoritative evidence reference. |

No command, path, serializer, handler reference, requester identity, recipe
mechanic, or closed family enum belongs in this envelope. The provider-owned
schema is `components/providers/contracts/provider-recipe.schema.json`.

The internal automation registry receives an explicit open family-to-contract
mapping and known-provider set from composition. It binds code by
`(provider-id, family-id)`. Loading valid definition data alone leaves the
recipe inert. Unknown providers/families, contract mismatches, duplicate
bindings, unsupported modes, and missing required ownership scope fail with
canonical provider errors.

## Automation modes

| Mode | Contract |
|---|---|
| `plan` | Preview without durable mutation. |
| `apply` | Make declared desired state real. |
| `prune` | Remove only state owned by supplied scope. |
| `status` | Read without durable mutation. |

A family exposes only modes it supports. No other public mode exists.
`probe`, `install`, `configure`, `verify`, `uninstall`, `dry_run`, and repair
selection are private mechanics. `apply` selects those mechanics from observed
state.

## Current automation families

| Family | Clients | Family input |
|---|---|---|
| CLI desired state | providers MCP; runtime/harness composition | CLI-specific desired state and options |
| Managed MCP entries | memory/Hindsight; coding-LSP; runtime/harness composition | Desired MCP entries and opaque ownership scope |
| Rules/hooks | memory/Hindsight | Desired contributions and opaque ownership scope |
| Plugin configuration | memory/Hindsight | Plugin-specific desired configuration and scope |
| Provider-specific configuration | memory/Hindsight; runtime/harness composition | Provider-family desired configuration and scope |
| Language-server projection | coding-LSP | Serializable language-server entries and scope |
| Generic LSP-MCP projection | coding-LSP | Serializable MCP entries and scope |
| Self-provided LSP support | coding-LSP | Support-specific desired state |
| Model projection | model management; runtime composition | Model-specific desired state and scope |
| Generated provider surfaces | runtime/composition callers | Desired contributions and scope |

Each family has its own public function, payload, result, and explicitly
registered provider implementation. Providers know provider and family, never
requester identity. Adding a family requires a current caller and an MA16
update.

## Boundary rules

- Requesters import only `providers_api`; providers import no requester domain.
- Foundation owns no provider capability, operation, or compatibility facade.
- Payload and result fields require current callers. No universal request,
  result, capability record, action taxonomy, `desired_present`, public
  `repair`, binding id, requester id, or recipe kind.
- Provider facts and evidence remain rich configuration, but cannot register,
  select, or enable automation. Explicit provider+family registration is sole
  authority.
- Duplicate registration fails deterministically; it never silently replaces a
  binding.
- Agent execution uses a separate provider-owned entry and explicit execution
  adapter composition. It has no operation mode or ownership scope.

## Migration rule

Backward compatibility is not maintained by default. Migrate every repository
caller and delete the obsolete function, alias, shim, dual route, and
compatibility test in the same family change. An exception requires a documented
external obligation approved before implementation.
