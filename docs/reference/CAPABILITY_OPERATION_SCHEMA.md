# Provider operation semantics

**Current planning authority:** MA16, MA17, and RV444 (2026-07-15).

This document defines caller semantics only. It is not a capability catalog
schema, Python object model, closed taxonomy, handler registry, or provider
configuration format.

## Boundary and authority

- Provider capability facts, evidence, and reference views belong to
  `components.providers` configuration/tooling (MA19). They are soft knowledge:
  they cannot register, select, or enable runtime behavior.
- Runtime provider behavior is enabled only by explicit provider registration.
- Requesters import only `audiagentic.components.providers.providers_api`.
  They never import provider recipes, adapters, catalog loaders, or serializers.
- Foundation owns no capability abstraction, facade, port, or compatibility
  re-export.

## One caller vocabulary

Every public provider operation uses one semantic mode:

| Mode | Caller meaning | Durable mutation |
| --- | --- | --- |
| `plan` | Preview how desired state would be made real or removed. | Never |
| `apply` | Make desired state real. | May mutate |
| `prune` | Remove only state owned by this operation's scope. | May mutate, owned state only |
| `status` | Read current state/check readiness. | Never |

`plan` and `status` are side-effect free by contract. `apply` is idempotent
where its provider operation supports idempotency. `prune` must preserve
unmanaged and other-scope state.

Public functions may retain family-specific payloads: model projection,
language-server desired entries, CLI desired state, MCP entries, hooks, and
plugins do not need one universal request shape. Each function receives the
payload it actually needs plus the semantic mode when more than one operation
is exposed. Do not create `CapabilityRecord`, universal `CapabilityRequest`,
or a field taxonomy merely to make these calls look uniform.

## Recipe mechanics are private

Provider recipes choose mechanics. `probe`, `install`, `configure`, `verify`,
`uninstall`, `dry_run`, and internal `prune`/`status` are not caller verbs.

- A CLI `apply` may probe, install, settle PATH, and verify.
- A managed-config `apply` may probe, diff, configure through MO06, report a
  collision, and request reload.
- A `prune` may remove an owned config entry or uninstall a wholly owned CLI
  artifact.
- A `status` may probe an executable or inspect managed ownership.

Current `ProviderRecipeRegistry` is an internal provisioning engine. It must
not leak its hard-coded lifecycle as public semantics. If a public operation
uses it, a providers-owned adapter maps semantic modes to that recipe's safe
mechanics. Config-mutation recipes can use the same adapter while delegating
diff/collision/reload to the MO06 managed-config core.

`ProviderRecipeKind` classifies implementation behavior only. It is not a
public capability universe and must not become a provider-fact taxonomy.

## Results

Results are shaped by current consumers, not by a universal envelope. When a
caller needs them, provider results expose structured outcomes such as:

- whether work changed state or was skipped;
- owned artifacts/actions and changed paths;
- collisions without overwriting unrelated state; and
- `reload_required` or action-needed guidance.

Provider-specific diagnostics remain provider-owned and redacted. Add a
first-class result field only when a current requester needs structured access;
otherwise retain detail in the provider result/details surface.

## Guardrails

- Config describes; explicit registration executes.
- No generated Python taxonomy from provider research.
- No caller chooses `install`, `configure`, `verify`, or `uninstall`.
- No catalog string can resolve a handler or execution transport.
- Agent execution is separate from provider operations; it has no operation
  mode, ownership scope, or catalog selection path.

## Historical material

The prior catalog schema and gateway algorithm were intentionally removed from
this reference. They described closed vocabularies, catalog-driven dispatch,
and foundation ownership now rejected by RV401/RV404/RV444. Preserve detailed
provider facts in MA19-owned configuration and evidence, not here.
