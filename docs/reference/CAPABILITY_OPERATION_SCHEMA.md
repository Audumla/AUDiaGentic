# Provider API contract

**Authority:** MA16. This document is the implementation contract for
`audiagentic.components.providers.providers_api`.

## API categories

Every public entry belongs to exactly one category.

| Category | Purpose | Operation mode |
|---|---|---|
| Resource/query | Manage or read AUDiaGentic-owned provider resources, descriptors, catalogs, and evidence | No |
| Automation family | Apply provider-specific automation to declared desired state | Supported subset of `plan`, `apply`, `prune`, `status` |
| Agent execution | Run an explicitly composed provider execution adapter | No |

Resource CRUD is not forced into operation semantics. Agent execution is not an
automation family. No universal gateway joins these categories.

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
