# Optional agent collaboration capability

**Status:** architecture decision and planning input, 2026-10-20. This is **not** a tracked plan item. Per `docs/planning/CREATING_PLANS.md`, create tracked items through `ag-planning` when that interface is available; do not hand-allocate plan IDs.

## Decision

Implement peer collaboration as an **optional capability/component layered over canonical Agents, Work and Gateway application APIs**. It is neither a gateway feature, a harness feature, an ACP extension requirement, nor an external forum dependency.

The capability owns topics, participant mappings, assistance requests, specialist matching, collaboration message history and reliable automatic response delivery. The existing gateway exclusively owns provider execution, admission, scheduling, session identity and lifecycle, verified output and recovery. Provider adapters continue to own transport-specific operations. A2A/ACP/MCP and Discord/web presentation are optional adapters, not collaboration authorities.

Disabled/absent collaboration must leave ordinary direct gateway requests, agent Work, roles, prompt composition, provider adapters and ACP/A2A flows unchanged. No mandatory runtime dependency or platform-specific launch code.

## Existing source contracts to consume

| Existing owner | Reuse | Do not duplicate |
| --- | --- | --- |
| `agents/models/agent_definition.py` | `advertised_skills`, role IDs, publication flags | A second global agent or expertise registry |
| `agents/capabilities/` + `configuration/resolution.py` | Role requirements, deterministic admission facts | A replacement AS84/AS85 launch-capability vocabulary |
| `agents/work/work_api.py`, `work/reviews.py` | Work submission, independent review work, waiting and terminal projections | Another Work state machine; do not require parent/child Work across distinct Agent Contexts |
| `agents/gateway/client.py` | Gateway session continuation, submission, status, verified output, controls and explicit resume | Direct provider process access, new scheduler, private gateway-store imports |
| `providers/providers_api.py`, session-surface declarations | Evidence-backed support for session capabilities | Guessing ACP/native steering support from protocol name |
| `agents/protocols/acp` and `agents/protocols/a2a` | Thin external interoperability where useful | Raw provider ACP proxies or an A2A-specific collaboration task engine |
| Existing observation, lifecycle and recovery journals | Existing execution evidence and recovery | Replacing execution evidence with collaboration message receipts |

Related plans: **AS84/AS85** (role/launch capability admission), **AS99** (outward ACP adapter), **AS100** (A2A and delegation), **AS97** (OpenCode ACP evidence), **PC14** (resumability facts), **SH25** (gateway execution queue), **SU04** (legacy `agent_jobs` retirement). This capability adds no new implementation steps or blockers to those plans.

### Distinct capability concepts

1. `advertised_skills`: declared **expertise** for finding collaborators; not execution permissions and not evidence of actual availability.
2. Role-required capabilities: existing **launch requirements** resolved and frozen by Agents/gateway admission.
3. Provider session-surface capabilities: evidence-backed **mechanisms** (open, resume, cancel, steer) exposed through existing APIs.

Do not collapse these into a single registry. Route by skill and project policy, then let canonical gateway admission reject unsupported or unauthorised execution. Treat skills as declarations; apply configured eligibility and optional explicit availability/validation before activation.

## Functional behaviour

An existing agent should be able to ask for a capability rather than name a target, e.g.

```json
{"topic_id":"optional-existing-topic","intent":"request","action":"review","skills":["concurrency"],"message":"Assess the recovery race","blocking":false}
```

The capability validates the authenticated/project-scoped origin, records an idempotent request and requester Work/Agent Context/session binding, selects an eligible registered Agent Definition using a **deterministic, documented** policy, and submits the selected agent's independent Work/turn through the public gateway API. Explicit mentions may optionally override matching, subject to the same admission rules.

The response is read **only after gateway-verified completion**, correlated to its request, journalled, and automatically delivered to the original requester session. The requesting agent must never need to poll an inbox, discover a peer's name, or manually issue a follow-up. Nonblocking work can continue; blocking work can use an existing dependency/waiting mechanism where appropriate. Failed/partial output is never published as verified success.

### Delivery and active turns

- **Idle/awaiting:** automatically submit a new correlated turn to the exact bound gateway session.
- **Busy:** prefer existing proven `steer-turn` when the actual resolved surface supports it; otherwise submit/queue a normal next turn through gateway FIFO. Steering is an optional optimisation, **not an MVP dependency or a reason to change the gateway/ACP adapters in this plan**.
- **Expired/unavailable:** use existing explicit, capability-checked gateway resume where valid. If continuation is not safe, persist an actionable undelivered outcome; no silent conversation replacement and no duplicate possibly submitted prompt.
- Track separately: accepted-for-delivery, gateway-admitted, provider-delivered/consumed when provable, and terminal response. A steering acknowledgement alone is not proof the model consumed the message.
- Coalesce multiple next-turn messages only under a deterministic, bounded policy, retaining the original event IDs and causal links.

The capability maintains its own small **inbox/outbox of collaboration delivery intents**, because the in-process foundation event bus is not durable external delivery. Do not create another execution queue. Use gateway events where available and reconcile pending intents from the existing public request/status surfaces after restart. Deduplicate inbound requests and outgoing activations with durable, project-scoped keys and session-generation fences.

### Independent context and visible history

A collaboration topic spans *multiple* Agent Contexts and gateway sessions. Store participant bindings to their authoritative IDs and immutable generation/scope, not copied provider session state. Canonical collaboration messages, outstanding requests and decisions are separate from gateway execution observations. Expose bounded initial context plus optional history/search reads; do not force agents to check for replies. No special case for a forum backend.

Human interfaces are projections: optional harness-facing MCP and/or a web/Discord adapter can read/post into the same topic under validated identities and project policy. None may launch providers, control sessions or decide completion on its own.

## Proposed implementation slices (unallocated plan IDs)

A. **Contract and routing:** optional component, topic/request/participant identities, read-only agent skill discovery, deterministic matching, authority boundaries and MCP capability projection.

B. **Async push coordinator:** public GatewayClient integration, request/reply correlation, auto-next-turn on busy/idle, crash-safe inbox/outbox and recovery, blocking/nonblocking delivery policy.

C. **Agent participation and prompt guidance:** narrow request/post/history tools; optional instructions teaching when to request independent review/deep dives, no mandatory autonomous LLM coordinator. Existing role/launch policies still govern what the selected agent may do.

D. **Human visibility (optional):** harness-facing UI and/or Discord adapter, no forum implementation leaked into the collaboration domain.

Any future **provider steering** work belongs in separately justified provider/session-surface conformance plans if existing controls are insufficient; it is not required for A–D and must not be baked into the collaboration component.

## Validation / acceptance

- Collaboration disabled: current gateway, Work, provider adapters, ACP and A2A behaviour remain unchanged, with no collaboration setup required.
- Codex asks for an unnamed concurrency review; policy deterministically picks an eligible agent based on `advertised_skills` and admission facts; another agent receives independent Work in its own context; the verified response automatically activates the original session.
- When requester is busy and steering is unsupported, follow-up is queued exactly once under existing session FIFO, without cancellation or another provider process owner.
- Restart after request acceptance, dispatch, terminal response and outbound delivery independently; no duplicate specialist execution or duplicate requester prompt.
- Wrong-project identity, mismatched generation, stale/busy session, failed review, missing skill and exhausted capacity all fail with explicit, bounded status.
- Tests prove no imports of gateway stores, provider adapters, ACP SDK or harness internals from collaboration; only documented public APIs are used.
- Human interfaces absent/present produce the same collaboration identities and outcomes; Discord is never a harness launcher.
- No automatic agent-to-agent echo loops: only directed pending requests or explicit subscriptions trigger activation, with budgets/depth limits.

## Planning status and boundaries

This is a **request for new plan item(s)**, not an implementation claim. The GitHub-only editing interface cannot use `plan_create_item`, so the existing tracked AS84/AS85 plans carry links to this design input without changing their scopes or inventing IDs. When ag-planning is available, deduplicate against open plans and register only the smallest independent slices needed. Avoid modifications to the gateway/harness core unless tests reveal a specific missing public capability, which should be planned separately with its owning component.
