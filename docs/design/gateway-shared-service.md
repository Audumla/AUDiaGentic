# Gateway shared-service readiness — decision record (EDJ13)

Status: **decided (v1)** — 2026-07-12
Scope: analysis only. This document records what the current in-process
gateway assumes, and what the v1 decision is. It adds no leases, owner
fields, idempotency fields, queues, migrations, or event topics.

## Context

The agents LLM gateway currently runs in-process: a module-level queue
manager owns dispatch, and blocking `wait`/`cancel` only work in the process
that submitted the request. The question this record answers: what must be
true before the gateway could run as a shared service used by many
AUDiaGentic instances, and what do we commit to now?

The enforced invariant that keeps this door open is the events-only
boundary: agent-jobs never imports the gateway's Python API — it publishes
`agents.llm.gateway.requested` / `agents.llm.gateway.cancel-requested` and
consumes `agents.llm.*` lifecycle events. This is verified by the executable
boundary test `tests/unit/jobs/test_gateway_boundary.py`.

## Same-process assumptions inventory

| Location | Current assumption | Shared-service failure mode |
| ------ | ---- | ---- |
| `agents_gateway_api.py:_QUEUE_MANAGER` (module-level `GatewayQueueManager()`) | One queue manager per process owns all profile queues and worker threads | Two instances each build their own queues over the same store: double-dispatch of the same persisted request; in-memory queue depths diverge from disk truth |
| `agents_gateway_api.py:wait_llm_request` | The waiting thread and the dispatching worker share a process (`_QUEUE_MANAGER.wait`) | A wait issued in instance A for a request dispatched by instance B never wakes; only disk polling would observe completion |
| `agents_gateway_api.py:cancel_llm_request` | The cancel target's queue/worker lives in this process (`_QUEUE_MANAGER.cancel`) | Cancel in instance A cannot interrupt a request running in instance B; only the persisted record flag would change, unobserved by B's worker |
| `agents_gateway_api.py:MAX_BLOCKING_TIMEOUT_SECONDS` (300s cap) | Blocking waits are a bounded same-process convenience | A service front-end holding sockets open for 300s per request does not scale; blocking semantics must not cross the instance boundary |
| `agents_gateway_store.py` per-project-root request records (`gateway_request_path`, per-request `threading.Lock` registry in `_request_locks`) | Single process is the sole writer; thread locks suffice for read-modify-write | Cross-process read-modify-write races (lost updates) on transition/cancel/attempt writes; thread locks provide no inter-process exclusion |
| `agents_gateway_api.py:reconcile_gateway_state` | Sole store ownership: any queued/running record found on startup is orphaned and safe to fail/reset | Run by instance A while instance B is mid-dispatch, it would mark B's live requests as orphaned — destructive reconciliation |
| `foundation/event/event_bus.py:347-359` (`EventBus._correlation_chains`) | Process lifetime is short (CLI-scoped); per-correlation event-id sets grow without eviction | A long-lived shared gateway service leaks memory per correlation id and could eventually mis-trip cycle detection on very long correlation chains |

## Decision table

| Concern | Decision | Rationale | Follow-up item |
| ------ | ---- | ---- | ---- |
| Inter-component / cross-instance contract | Events are the sole contract (`agents.llm.gateway.requested`, `agents.llm.gateway.cancel-requested`, `agents.llm.*` outcomes) | Already implemented and enforced by the boundary test; event payloads/metadata carry every join key (`job-id`, `correlation_id`, `request-id`) needed to survive an instance boundary | none |
| Direct blocking APIs (`run_llm_request`, `wait_llm_request`, `cancel_llm_request` as Python calls) | Retain as same-process conveniences; never expose across instances | They exist for MCP tools and tests in the owning process; making them remote would import all the failure modes above for no current consumer | none |
| Queue ownership (`_QUEUE_MANAGER`) | Defer multi-instance ownership (leasing/locking) until a second gateway instance is an approved requirement | No consumer exists; designing leases now is speculative (arch-standards: avoid premature abstraction) | none (raise when requirement approved) |
| Store concurrency (per-request thread locks) | Defer inter-process locking with queue ownership | Same trigger condition; thread locks are correct for the single-process reality | none (raise with queue ownership) |
| Destructive reconciliation (`reconcile_gateway_state`) | Document as single-owner-only; defer guarding until multi-instance work begins | Harmless today; must gain an ownership check in the same change that introduces a second owner | none (raise with queue ownership) |
| `EventBus._correlation_chains` unbounded growth | Accept for CLI-lifetime processes; any long-lived service work must bound or evict chains | Leak is proportional to distinct correlation ids per process lifetime — negligible for CLI runs, real for a daemon | none (row re-opens when a long-lived service is approved) |
| Correlation-key survival across instances | Already satisfied: correlation keys travel in event metadata, not process state | observability-standards requirement met by the events-only contract | none |

## Non-goals

- No leasing, ownership, or idempotency fields on gateway records.
- No remote/networked gateway API, no service daemon, no second instance.
- No new event topics and no changes to existing payload shapes.
- No store migration or file-locking scheme.
- No eviction policy implementation for `_correlation_chains` (documented
  only).

All follow-up rows are `none` under the v1 decision: multi-instance work is
deferred until a second gateway instance is an approved requirement, at which
point the deferred rows above convert into concrete plan items.
