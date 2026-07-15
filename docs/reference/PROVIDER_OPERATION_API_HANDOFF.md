# Provider operation API handoff — MA16

**Status:** High-value contract frozen 2026-07-15. Mid-level implementation
work may begin only against these packets.

## Non-negotiable boundary

Requesters import only `audiagentic.components.providers.providers_api`.
They receive family-specific functions and plain result mappings. They do not
receive `ProviderRecipeRegistry`, `ProviderRecipeKind`, recipe classes, recipe
results, binding ids, handlers, paths, serializers, or lifecycle methods.

Public semantics are exactly:

| Mode | Guarantee |
| --- | --- |
| `plan` | no durable mutation |
| `apply` | make declared desired state real |
| `prune` | remove only declared owned scope |
| `status` | no durable mutation |

Family payloads stay specific. No generic request dispatcher or universal
result object may be added.

## MA12 packet — provider CLI

High-value owner must approve exact existing CLI result golden before work.

Target public operation: provider CLI family adapter with `mode` plus the
current caller-required repair intent. `apply` selects install/repair mechanics
inside providers; `plan` previews the selected action; `prune` removes only
CLI state owned by the provider lifecycle; `status` reads/probes.

Keep existing provider-MCP tool names (`install_provider`, `uninstall_provider`,
`repair_provider`) as compatibility endpoints until MA12 migrates them. They
must adapt internally; requester components must not call mechanic-named API
functions.

## MA17 packet — agent execution

Target public function accepts project root, provider id, agent-selected model
id/alias, and existing neutral packet data. Providers perform enabled check,
provider-config load, model resolution, and adapter execution. Agents retain
profile resolution, retry/fallback policy, cancellation, correlation, and
timeline persistence.

Preserve normalized result mapping and existing `AudiaGenticError` codes. Do
not make execution a provider-operation mode.

## MA08 packet — Coding-LSP

Use separate family functions for language-server desired entries, generic LSP
MCP entries, and self-provided LSP support. Inputs are serializable mappings
and opaque managed ids/scopes; no `coding_lsp.LanguageServerEntry` crosses into
providers. Each function exposes only meaningful semantic modes. Preserve the
five current response shapes until caller migration goldens approve change.

## MA02 packet — Hindsight

Memory supplies backend-derived desired values and opaque ownership scopes.
Providers own MCP/hook/plugin/Codex/Pi mechanics, paths, serializers, repair,
and registrations. Migrate one family at a time in this order: MCP, hooks,
plugins/repair, Codex/Pi, guidance/status. Each family needs golden behavior,
non-mutation plan/status proof, adoption/collision proof, scoped prune proof,
and redaction proof before old memory mechanics are deleted.

## Mid-level stop conditions

Stop and return to high-value owner if any task needs:

- a new public field/signature or mode;
- result/error compatibility choice;
- ownership/adoption/collision interpretation;
- provider registration choice;
- change to retry/cancel/timeline behavior; or
- deletion outside the approved file/symbol list.
