# Provider operations and agent execution boundaries

**Current planning authority:** MA17 and RV444 (2026-07-15).

## Two separate boundaries

Provider operations and agent execution are separate concerns.

| Boundary | Caller intent | Authority |
| --- | --- | --- |
| Provider operation | `plan`, `apply`, `prune`, `status` against a provider-owned operation | explicit provider registration |
| Agent execution | run an agent invocation, stream normalized events, cancel | explicit execution-adapter composition |

Provider operations have ownership scopes and managed-state outcomes. Agent
execution does not. Neither boundary reads provider capability research to
select a handler, adapter, or transport.

## Provider operations

Requesters may import only `audiagentic.components.providers.providers_api`.
That public module may offer family-specific functions because their payloads
differ. Each function uses the same four operation meanings defined in
`CAPABILITY_OPERATION_SCHEMA.md`; it does not expose recipe method names.

Providers own public-mode adaptation and internal mechanics:

1. validate only fields a current operation needs;
2. resolve an explicitly registered provider implementation;
3. invoke recipe/config mechanics appropriate to that implementation;
4. enforce side-effect freedom for `plan`/`status` and scoped ownership for
   `prune`; and
5. return only result fields current callers consume, with redacted details.

No universal request envelope is required. No catalog lookup, support-state
short-circuit, binding id, dotpath, or transport string participates in this
path.

## Agent execution

MA17 derives the smallest honest agents-to-providers execution boundary from
actual call sites. Provider adapters are explicitly composed. Existing neutral
ACP primitives remain foundation-owned only where independently provider
neutral. Execution preserves one redacted, bounded ordered timeline and
supports cancellation/fallback requirements proven by MA18.

## Architecture checks

- Foundation has no capability package, type, port, or facade.
- Requesters import only `providers_api`; providers do not import requester
  domains.
- Explicit registration is runtime authority; provider research/config is not.
- Recipe method names and `ProviderRecipeKind` never become public caller
  protocol or capability taxonomy.
- Provider operations and execution have independent tests and no hidden
  catalog-driven coupling.

## Historical material

The previous gateway/resolver algorithm is removed. It depended on a
foundation catalog, closed support/transport taxonomy, and catalog-selected
bindings rejected by RV401/RV404/RV444.
