<!-- MANAGED_BY_AUDIAGENTIC: generated reference doc -->

# Pi ACP Status-Mapping Report

**Date:** 2025-07-11  
**Plan items:** AS19, AS21, AS27  
**Scope:** Pi ACP implementation, AS28 neutral session transport, and the smallest code-level path to map Pi activity/tool/permission/terminal evidence without protocol leakage.

---

## 1. Exact files/symbols where Pi ACP can emit TransportObservation

### 1.1 Launch builder

| File | Symbol | Role |
|------|--------|------|
| `src/audiagentic/components/providers/adapters/pi/acp.py` | `_managed_pi_acp()` | Resolves the managed `pi-acp` bridge binary from the global harness runtime |
| `src/audiagentic/components/providers/adapters/pi/acp.py` | `build_acp_launch()` | Builds an `AcpLaunch` with project-root, optional model-id, and request-runtime-root environment |

The launch builder is registered through `load_acp_launch_builder("pi")` in `providers/services/execution.py` (loaded from the adapter's YAML descriptor).

### 1.2 Transport creation and observation emission

| File | Symbol | Role |
|------|--------|------|
| `src/audiagentic/foundation/transports/acp.py` | `AcpSessionTransport.open()` | Spawns the child, initializes the ACP protocol, creates the session — emits no observations itself (protocol handshake only) |
| `src/audiagentic/foundation/transports/acp.py` | `AcpSessionTransport.prompt()` | Runs one turn; each `_TurnPipeline.emit()` call produces an `AcpEvent` that is forwarded through the callback pipeline |
| `src/audiagentic/foundation/transports/acp.py` | `_TurnPipeline.emit()` | The per-turn bounded-event delivery — normalizes raw ACP `sessionUpdate` kinds to canonical kinds via `_map_kind()`, then yields `AcpEvent` instances |
| `src/audiagentic/foundation/transports/acp.py` | `AcpAgentSessionTransport.prompt()` | Wraps the inner transport, maps each `AcpEvent` → `TransportObservation` via `_map_acp_event_to_observation()`, and delivers through the neutral `ObservationSink` protocol |
| `src/audiagentic/foundation/transports/acp.py` | `_map_acp_event_to_observation()` | **The exact mapping function**: converts raw ACP event frames to bounded `TransportObservation` values. This is the single point where Pi (and all ACP providers) emit neutral observations |
| `src/audiagentic/foundation/transports/acp.py` | `_ACP_KIND_TO_TRANSPORT` | Maps known ACP canonical kinds to `TransportObservationKind`: `assistant-message` → ACTIVITY, `thought` → ACTIVITY, `status` → ACTIVITY, `usage` → ACTIVITY, `result` → TERMINAL, `error` → TRANSPORT_ERROR |
| `src/audiagentic/foundation/transports/acp.py` | `_KIND_VOCABULARY` | Closed set of canonical ACP kinds: `{assistant-message, thought, status, usage, tool-call, file-change, terminal-output, plan-update, permission-request, error, result}` |
| `src/audiagentic/foundation/transports/acp.py` | `_RAW_TO_CANONICAL` | Maps raw ACP `sessionUpdate` strings to canonical kinds (e.g., `agent_message_chunk` → `assistant-message`, `tool_call_update` → `tool-call`) |

### 1.3 Observation delivery chain (gateway session path)

| File | Symbol | Role |
|------|--------|------|
| `src/audiagentic/components/agents/agents_gateway_sessions.py` | `_observation_sink()` (inside `_prompt()`) | Receives each `TransportObservation`; routes through the observer lease (if acquired) and the turn-event callback |
| `src/audiagentic/components/agents/agents_gateway_turn_events.py` | `_make_on_event_callback()` | Builds the per-turn event projector; publishes to event bus topics (`TURN_MODEL_STARTED_TOPIC`, `TURN_TOOL_STARTED_TOPIC`, etc.) and records session timeline events |
| `src/audiagentic/components/agents/agents_gateway_turn_events.py` | `_TurnEventProjector.resolve()` | Maps `TransportObservationKind` → turn event topic: ACTIVITY → model-started, TERMINAL → model-completed, TOOL_REQUESTED → tool-started, TOOL_FINISHED → tool-completed |

---

## 2. Observation kinds/correlation presently available for Pi ACP

### 2.1 TransportObservationKind coverage (from `_map_acp_event_to_observation`)

| ACP canonical kind | TransportObservationKind | Attributes carried |
|---------------------|--------------------------|--------------------|
| `assistant-message` | ACTIVITY | none (text is extracted for overflow buffer, not attributes) |
| `thought` | ACTIVITY | `model_activity` (if text present) |
| `status` | ACTIVITY | none |
| `usage` | ACTIVITY | none |
| `result` | TERMINAL | `stop_reason`, `error_code` (if error present) |
| `error` | TRANSPORT_ERROR | `error_code`, `reason` |
| `tool-call` + status in `{pending, started, in_progress}` | TOOL_REQUESTED | `tool_call_id`, `tool_status` |
| `tool-call` + status in `{completed, finished, failed, cancelled}` | TOOL_FINISHED | `tool_call_id`, `tool_status` |
| `tool-call` + unknown status | TRANSPORT_UNKNOWN | none |
| `permission-request` | PERMISSION_REQUESTED | `tool_call_id` |
| any unmapped kind | TRANSPORT_UNKNOWN | none |

### 2.2 Correlation quality

All Pi ACP observations carry `CorrelationQuality.REQUEST_SCOPED` — they are scoped to the current prompt request but lack a native protocol-level correlation identifier (ACP does not expose one on `sessionUpdate`).

### 2.3 What is NOT mapped (missing kinds)

| ACP canonical kind | Mapped? | Reason |
|---------------------|---------|--------|
| `file-change` | No | Not in `_ACP_KIND_TO_TRANSPORT`; falls through to TRANSPORT_UNKNOWN with no attributes |
| `terminal-output` | No | Not in `_ACP_KIND_TO_TRANSPORT`; falls through to TRANSPORT_UNKNOWN |
| `plan-update` | No | Not in `_ACP_KIND_TO_TRANSPORT`; falls through to TRANSPORT_UNKNOWN |

### 2.4 Control capability (from `AcpAgentSessionTransport.control()`)

| SessionControlAction | Disposition | Notes |
|----------------------|-------------|-------|
| CANCEL_TURN | ACCEPTED | Sets cancel signal; raced inside `_inner.prompt()` |
| INTERRUPT_TURN | UNSUPPORTED | ACP has no interrupt protocol support |
| STEER_TURN | UNSUPPORTED | ACP has no steer protocol support |
| RESPOND_PERMISSION | UNSUPPORTED | ACP permission response requires versioned proof; default-deny |
| CLOSE_SESSION | ACCEPTED | Delegates to `_inner.close()` |

---

## 3. AS19/AS21 path: smallest code-level mapping without protocol leakage

### 3.1 Current Pi ACP evidence flow (what works today)

```
AcpSessionTransport._SessionClient.session_update()
    → _TurnPipeline.emit(raw_kind, payload)
        → AcpEvent(kind=canonical, ext={acp: {raw_kind, status, tool_call_id, ...}})
            ↓ callback
AcpAgentSessionTransport.prompt(_wrapped_sink)
    → _map_acp_event_to_observation(acp_event, ag_sid, turn_id)
        → TransportObservation(kind, ag_session_id, turn_id, sequence, attributes)
            ↓ sink delivery
agents_gateway_sessions._observation_sink(obs)
    ┌→ [OBSERVER LEASE — SKIPPED for Pi (see §4)] ───────────────┐
    └→ _on_event_cb(obs)                                         │
        → _TurnEventProjector.resolve()                           │
            → event bus publish (TURN_MODEL_STARTED_TOPIC, etc.)  │
            → session timeline record                             │
```

### 3.2 Where the AS19 path breaks for Pi

The observer lease is **NOT** acquired for Pi sessions because `pi-rpc` and `pi-community-acp` both have:

- `validation_state = PROBE_REQUIRED` (not VALIDATED)
- `effective_production_level = O0` (not ≥ O1)
- `lifecycle_source = LifecycleSource.NONE` (not TRANSPORT)

The gate in `resolve_transport_observation_lease()`:

```python
if not is_eligible_transport_observation_publisher(
    request.provider_id, request.surface_id, platform=platform,
):
    return StatusObserverResult(ok=False, supported=False, state=UNSUPPORTED, ...)
```

`is_eligible_transport_observation_publisher()` requires all three gates to pass:

1. `validation_state == VALIDATED`
2. `effective_production_level.numeric >= 1`
3. `lifecycle_source == LifecycleSource.TRANSPORT`

### 3.3 Smallest code-level path to enable AS19/AS21 for Pi

**Path A — Validate Pi in AS27 inventory (minimal invasive change):**

1. In `harness_observability_inventory.py`, add probe evidence for Pi:
   - Set `validation_state = VALIDATED` for `pi-rpc`
   - Set `effective_production_level = O1`
   - Set `lifecycle_source = LifecycleSource.TRANSPORT`
   - Add `supported_statuses = {"model-thinking", "tool-calling", "waiting-permission"}` (or the actual statuses Pi ACP emits)
   - Add `probe_anchor` pointing to a Pi-specific e2e test
   - Add `platform_evidence` tuple with validated platforms

2. Register Pi's AS27 capability descriptor:
   - In `providers/contracts/harness_status_observer.py`, Pi adapter must declare its `HarnessStatusObserverCapability` (mechanism, supported_statuses, lifecycle_installation). Currently only OpenCode ACP declares this via the provider descriptor; Pi has none.

3. Wire the observer lease through the existing path:
   - No code change needed in `agents_gateway_sessions.py` — the `_open_session()` already calls `providers_api.open_harness_status_observer()` and acquires the lease when resolution succeeds.
   - The `_observation_sink()` already routes through the lease into `StatusEvidenceSink` → `SessionEvidenceProjection`.

**Path B — Add Pi-specific observer adapter (if AS27 validation is deferred):**

If full AS27 validation for Pi is pending, a separate observer adapter could be added:

1. Create `providers/adapters/pi/observer_adapter.py` with a `HarnessStatusObserverCapability` declaring `TRANSPORT_OBSERVATION`.
2. Register it in the provider descriptor or adapter factory so the resolver discovers it.
3. The generic normalizer (`normalize_harness_status_observation`) would handle the normalization without Pi-specific code — it only reads `TransportObservationKind` and maps to canonical status strings.

**Either path produces no protocol leakage:** The `_map_acp_event_to_observation()` function already strips raw ACP kind names and payloads — unknown kinds produce TRANSPORT_UNKNOWN with no attributes, and known kinds carry only the bounded attribute keys defined in `_ALLOWED_ATTRIBUTE_KEYS`.

---

## 4. Missing evidence — precise gaps

### 4.1 AS27 inventory gaps (blocking AS19 for Pi)

| Gap | Location | Impact |
|-----|----------|--------|
| `pi-rpc` not validated | `harness_observability_inventory.py` line ~271 | Observer lease never acquired; AS19 evidence pipeline never activated |
| `pi-community-acp` not validated | `harness_observability_inventory.py` line ~283 | Same; this surface is community-maintained anyway (lower priority) |
| No `probe_anchor` for Pi ACP e2e test | inventory | Cannot promote without evidence |
| No `platform_evidence` for Pi ACP | inventory | Cross-platform eligibility unknown |
| No `HarnessStatusObserverCapability` declared by Pi adapter | `providers/adapters/pi/` — missing file | Provider descriptor has no capability declaration; resolver cannot discover Pi's observation mechanism |

### 4.2 Transport observation gaps (ACP protocol limits)

| Gap | Location | Impact |
|-----|----------|--------|
| `file-change` kind → TRANSPORT_UNKNOWN | `_map_acp_event_to_observation()` | File modification events are invisible to the status pipeline |
| `terminal-output` kind → TRANSPORT_UNKNOWN | `_map_acp_event_to_observation()` | Terminal command output is invisible to the status pipeline |
| `plan-update` kind → TRANSPORT_UNKNOWN | `_map_acp_event_to_observation()` | Plan changes are invisible to the status pipeline |
| No `TOOL_FINISHED` status for non-terminal tool states | `_map_acp_event_to_observation()` | Tool-call events with unknown status drop to TRANSPORT_UNKNOWN (no tool name, no args — just lost) |
| `RESPOND_PERMISSION` → UNSUPPORTED | `AcpAgentSessionTransport.control()` | Permission responses cannot be routed back through the transport; default-deny is always applied inside `_SessionClient.request_permission()` |

### 4.3 Evidence pipeline gaps (what the status projection does not receive from Pi)

| Gap | Impact |
|-----|--------|
| No terminal inference from observer data | AS21 `SessionEvidenceProjection` explicitly rejects terminal statuses — this is by design, not a bug. Terminal evidence must come from turn-state pipeline (TERMINAL observation + timeline), not status observation |
| `CorrelationQuality.REQUEST_SCOPED` only | ACP does not expose native correlation IDs on `sessionUpdate`; all observations are request-scoped, never CORRELATED |
| No semantic-strength upgrade | All Pi evidence carries `semantic_strength = UNKNOWN` and `verification_tier = "unknown"` — the inventory has no proof that Pi's event stream is semantically reliable |
| No TURN_ACCEPTED observation emitted | ACP does not emit a turn-accepted frame; this kind exists in the closed vocabulary but no provider emits it yet |

### 4.4 Control evidence gaps

| Gap | Impact |
|-----|--------|
| `INTERRUPT_TURN` unsupported | Cannot interrupt mid-tool-call for Pi sessions |
| `STEER_TURN` unsupported | Cannot append steer text to Pi turns |
| `RESPOND_PERMISSION` unsupported | No versioned proof that ACP accepted a permission response; the policy_fn inside `_SessionClient.request_permission()` is the only path, and it runs synchronously during the turn (no decoupled response) |

---

## 5. AS19/AS21 evidence flow — current vs. target for Pi

### Current state

```
Pi ACP events → TransportObservation → [observer lease: SKIPPED] → turn-event pipeline only
                                                                              ↓
                                                                    session timeline + event bus
                                                                    (no StatusEvidence, no AS21 projection)
```

### Target state (after AS27 validation of Pi)

```
Pi ACP events → TransportObservation → observer lease
                                          ↓
                                  StatusEvidence (via normalize_harness_status_observation)
                                          ↓
                                  StatusEvidenceSink (binding validation, monotonic dedup, scalar allowlist)
                                          ↓
                                  SessionEvidenceProjection (maps to EvidenceKind, feeds project_session_lifecycle)
                                          ↓
                                  SessionLifecycleDecision → AS21 coarse-state + decision flags
                                                                              ↓
                                                                    session_runtime_status() redacted snapshot

Parallel (unchanged): TransportObservation → turn-event pipeline → timeline + event bus
```

---

## 6. Protocol leakage audit

The Pi ACP path is **protocol-clean** — no raw ACP data leaks into the neutral observation contract:

- `_map_acp_event_to_observation()` maps to closed `TransportObservationKind` enum; unknown kinds produce TRANSPORT_UNKNOWN with no attributes
- Attribute keys are validated against `_ALLOWED_ATTRIBUTE_KEYS` per kind (e.g., ACTIVITY allows only `model_activity`)
- No raw ACP kind name, payload, or provider session ref is carried in `TransportObservation`
- The `_TurnPipeline.emit()` preserves `raw_kind` only inside `AcpEvent.ext["acp"]`, which never crosses the provider adapter boundary (stays within `acp.py`)
- Compact mode further strips payload from retained events

**No protocol leakage exists on the Pi path.** The gaps are in evidence *coverage* (missing kind mappings, missing AS27 validation), not in evidence *integrity*.

---

## 7. Summary of required actions for AS19/AS21 mapping

1. **Probe and validate Pi ACP** — write an e2e test proving Pi ACP event schema, correlation, and lifecycle semantics (maps to `probe_anchor` in inventory)
2. **Promote Pi in AS27 inventory** — set `validation_state = VALIDATED`, `effective_production_level = O1`, `lifecycle_source = TRANSPORT` for `pi-rpc`
3. **Declare Pi capability** — add `HarnessStatusObserverCapability` to the Pi provider descriptor
4. **Add missing kind mappings** (optional but recommended) — map `file-change`, `terminal-output`, and `plan-update` ACP kinds to appropriate TransportObservationKind values in `_ACP_KIND_TO_TRANSPORT`
5. **Wire the existing path** — no additional code changes needed; the observer lease acquisition, evidence sink, and projection are already in place in `agents_gateway_sessions.py`
