# Capability gateway and execution resolver — design spec (MA17)

> **Partially superseded by RV401/RV402 (2026-07-14).** Do not implement
> immutable `CapabilityRecord`, catalog-driven handler resolution, support-state
> filtering, transport-manifestation selection, or declaration preferences.
> Preserve neutral request/result boundaries, explicit provider composition,
> execution ports, event normalization, timeline/cursor, cancellation, and
> redaction. Current authority: MA17. Runtime availability comes from explicit
> handler/adapter registration; provider capability catalog remains soft config.
> RV404 also removes capability request/result/gateway ownership from
> foundation: these belong to the providers public API. Approved requesters may
> depend on that narrow public API; foundation capability ports are forbidden.

Historical status: **T3 design frozen 2026-07-14, NOW REOPENED IN PART**
(RV382). This was the implementation contract for MA17 Steps 3–9. MA17 now
governs implementation; catalog-driven sections below are historical only.

## 1. Two distinct contracts — never merged

- **Capability gateway** — configuration/lifecycle operations
  (`plan|apply|prune|status` requests against declared capabilities).
  Synchronous request/result. Owns validation, support-state short-circuit,
  handler resolution, result normalization.
- **Execution resolver** — resolves a *need to run an agent* into a typed
  execution port. No request modes, no ownership scopes. Owns transport
  selection only. The agents gateway calls it; it never calls the capability
  gateway, and the capability gateway never executes agents.

Historical design used one immutable capability record from the MA16 loader.
RV401/RV402 replace that input with minimal request/result types and explicit
provider composition. Neither contract reparses provider knowledge config.

## 2. Capability gateway request path

Pipeline (each stage has exactly one owner):

1. **Validate** request against schema §4 — requester-suppliable fields only
   (`provider-id, capability-id, operation, payload, ownership-scope,
   correlation-id`). Unknown field or requester-supplied binding/path/handler
   ref → `VAL-CAP-001` result, handler never resolved.
2. **Resolve record** — `(provider-id, capability-id)` in the loaded catalog.
   Missing → canonical `unsupported` result (not an exception).
3. **Support-state short-circuit** — `manual` → `action-needed` with the
   declaration's manifestation text; `blocked` → `blocked` with blocker text;
   `unsupported`/`unverified` → `unsupported`. Handlers are NEVER invoked for
   these states. Mode declared `not-applicable` → `unsupported` result.
4. **Resolve handler** — via the provider composition root's typed binding
   registry (§5), keyed by the record's opaque `binding` id. Exactly one
   handler; missing binding for a `supported` capability is a composition
   defect → canonical error result, never a fallback direct call.
5. **Invoke** in requested mode. `plan`/`status` must cause zero durable
   mutation (enforced by contract tests, not trust). `apply` idempotent.
   `prune` scoped to the request's `ownership-scope` only.
6. **Normalize result** — handler output maps through the single foundation
   status normalizer (schema §7). Exceptions map to `error` results with
   canonical codes; raw exception text goes to redacted diagnostics.
   `correlation-id` echoes verbatim.

Handler protocol (typed, foundation-owned):

```python
class CapabilityHandler(Protocol):
    def handle(self, request: CapabilityRequest) -> CapabilityResult: ...
```

Handlers receive the validated neutral request only — no requester/domain
identity, no ability to branch on it (architecture test: fixture requester
swap yields byte-identical handler inputs).

## 3. Execution resolver contract

```python
@dataclass(frozen=True)
class ExecutionNeeds:
    provider_id: str
    required: frozenset[str]      # feature ids: "session", "live-events",
                                  # "cancel", "permission-exchange"
    preferred_transports: tuple[str, ...] = ()   # optional caller preference

class ExecutionPort(Protocol):
    async def run(self, invocation: ExecutionInvocation,
                  on_event: EventCallback | None = None,
                  cancel_signal: asyncio.Event | None = None) -> ExecutionResult: ...
```

`ExecutionInvocation` carries prompt, cwd (authoritative working root from
the agents gateway), model/profile overrides, stream controls.
`ExecutionResult`/events are the frozen neutral event contract — the port
adapts `AcpResult`/CLI output into it; the ACP types themselves never cross
the port.

## 4. Transport selection algorithm (pure function, fully table-testable)

Input: the record's ordered `transports` list + `ExecutionNeeds`.

1. Filter to `state: verified` on a `support: supported` capability.
   (`unverified` transports are never selectable — no override parameter.)
2. Filter to entries satisfying every `required` feature
   (`session: persistent` for "session", `events: incremental` for
   "live-events", `cancel: supported`, `permissions: interactive`).
3. Apply `preferred_transports` order if given, else declaration order.
4. First survivor wins → typed `TransportSelection(transport, record-ref)`.
5. No survivor → canonical `ExecutionUnsupported(reason)` naming the first
   unsatisfied filter — never an exception, never a silent downgrade.

Forbidden anywhere in gateway/resolver code: `if provider_id`,
`if transport == "acp"`, executable names, protocol versions. Those facts
live only in declarations and provider-owned bindings. Pinned test table:
ACP preferred; CLI fallback when ACP absent; unverified rejected;
required-feature mismatch rejected; empty transports → unsupported.

## 5. Binding registration protocol (both contracts)

- Providers register `{binding-id → handler | port-factory}` at their
  composition root through a typed registry (protocol owner: foundation;
  key owner: providers; declaration source: MA16 catalog).
- Registration is explicit code, visible in the resolved binding graph —
  no importlib/dotpath loading from declaration strings, ever.
- Duplicate binding-id → canonical error at registration time. Unknown
  binding-id at resolve time → composition defect result (§2.4).
- Test/plugin replacement allowed only via explicit composition-root
  substitution, which shows in the binding graph.

## 6. Event projection and caller delivery (Steps 7–9)

- The execution port's neutral events are redacted FIRST, then projected
  into the EXISTING agents-gateway timeline/event persistence — no new
  store, no raw ACP/stdout persistence. Frozen-contract bounds apply
  before persistence.
- Sequence, session-id, kind, terminal flag persist as first-class columns;
  `ext` persists only post-redaction.
- **Cursor semantics**: `after_sequence + limit` → `(events, next_cursor,
  exhausted)`. Same persisted sequence replayed identically; `next_cursor`
  stable across polls; `exhausted` true only after the terminal event is
  delivered.
- MCP cursor polling is the portable baseline. Progress notifications are an
  optional projection off the same callback — failure-isolated (a progress
  failure never affects the run or the timeline).
- Cancellation: one terminal state; resolver port forwards `cancel_signal`
  to the transport (frozen contract owns child termination).

## 7. What stays where (ownership recap)

| Concern | Owner |
|---|---|
| Request/result types, handler+port protocols, status normalizer | foundation |
| Catalog consumption, capability gateway, execution resolver, binding registries, OpenCode ACP+CLI port adapters | providers (composition root) |
| Profile/model selection, retry/fallback, queue, request records, timeline persistence, cursor/progress projection | agents gateway |
| Neutral event contract, ACP transport internals | foundation/execution (frozen) |

## 8. Implementation order for T2 (per MA17 steps)

Steps 3–6 (gateway, resolver, selection, OpenCode binding) build to this
spec once the MA16 loader lands — then STOP for the architecture review
checkpoint pinned in MA17 before Steps 7–9 (agents-gateway edits). Step 12's
test list maps 1:1 onto §2–§6 above. Remaining T3 in MA17 after this spec:
the Steps 0–6 checkpoint review itself, Step 10 cleanup rulings, and the
Step 11 BU01-gated release→ledger event decision.
