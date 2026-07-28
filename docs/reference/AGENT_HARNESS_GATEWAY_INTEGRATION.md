# Agent Harness Gateway Integration Guide

This guide is the implementation checklist for making an agent harness usable
through the gateway. It is provider-neutral, with Pi used as the concrete
example. A harness is not gateway-ready merely because its command starts: the
provider must be provisioned, registered, launched, isolated, observable,
recoverable, and covered by end-to-end tests.

## 1. Ownership and reuse

Keep provider-specific code small and use the existing generic seams:

- **AS13** owns managed ACP bridge installation and model-faithful launch
  dependencies. Production must use the managed, pinned runtime; do not rely on
  an implicit global install or `npx`.
- **AS17** owns child-process evidence, process-tree supervision, cancellation,
  timeout, crash handling, and cleanup.
- **AS28** owns the provider-neutral `AgentSessionTransport` and session
  capability surface.
- **SH11** owns the gateway runtime factory and implementation selection.
- **SH16** owns Pi-specific adapter wiring, request-local Pi state, capability
  evidence, and Pi tests.

Do not create a second process manager, ACP transport, gateway runtime factory,
or provider-neutral session abstraction for an individual harness.

## 2. Provider registration

Add a provider descriptor under `src/audiagentic/config/providers/` containing:

1. A stable provider id and display metadata.
2. Explicit model resolution and model forwarding rules.
3. An execution adapter or execution block that the gateway runtime factory can
   resolve. Provider selection without this registration reaches launch and then
   fails with `VAL-EXEC-002`.
4. The declared execution isolation tier. This is a contract, not a label:
   only claim `full-isolation` after concurrent gateway execution has proved the
   claim.
5. Session capabilities: ACP/native protocol, progress events, cancellation,
   resume, and terminal-state behavior.
6. Runtime provenance: harness version, bridge version, adapter version, and
   the managed runtime fingerprint.

The gateway profile registry owns profiles globally. A project requests a
profile snapshot and receives a session-specific execution. Queue limits and
profile configuration must therefore be coordinated by the gateway, while
project work and request state remain associated with the caller's request.

## 3. Managed provisioning

Create a recipe at
`src/audiagentic/config/provisioning/harness/<harness>.yaml` with pinned
versions for every executable involved in the launch:

- harness CLI/runtime;
- MCP adapter, if used;
- ACP bridge, if used;
- language/runtime packages and required extras.

The provider lifecycle owns the installation scope. It may install a harness
CLI and required bridge packages globally when that is the harness's supported
native layout, or into a managed runtime when the provider contract declares
one. In either case, the probe and launch adapter must resolve the same concrete
installation rather than silently falling back to an unrelated copy on PATH.
Validate a clean installation through AUDiaGentic in Docker, including the
model-loading rig used by the project. Record install warnings separately from
install failure; unrelated malformed user config must not silently make the
install appear successful.

For Pi, the production ACP command is the separately installed `pi-acp`
adapter. `pi --rpc` is Pi's native JSONL mode and is not ACP. The adapter must
resolve the managed `pi-acp` executable and fail closed when it is absent
(`RES-PIACP-001`).

## 4. Launch contract

The provider adapter must construct a deterministic launch request containing:

- the requested repository as `cwd`;
- the resolved model id, when the request specifies one;
- the request-local session directory, when the harness supports one;
- an allowlisted child environment;
- a runtime fingerprint and request id for provenance.

The gateway must launch through the generic process/session seam and retain the
child identity before accepting the request as running. The command, arguments,
cwd, environment policy, and resolved versions must be inspectable in job
diagnostics without exposing secrets.

## 5. Request-local state and isolation

Each request gets a unique runtime root, for example:

```text
<gateway-runtime>/agents/<request-id>/
  manifest.json
  pi/agent/
  pi/sessions/
  tmp/
  cache/
```

For Pi:

- set `PI_CODING_AGENT_DIR` to the request-local `pi/agent` directory;
- pass `--session-dir` explicitly to `pi-acp` when supported;
- keep `cwd` as the requested repository;
- redirect `HOME`, `USERPROFILE`, `HOMEDRIVE`, `HOMEPATH`, `APPDATA`,
  `LOCALAPPDATA`, `TEMP`, `TMP`, and relevant XDG directories on Windows;
- never mutate the gateway's own environment;
- write the manifest before launch and add pid/process identity after launch.

This is agent-state isolation, not filesystem or security containment. A shared
checkout still shares its working tree and project `.pi` resources. Do not
promote the provider's isolation tier without tests proving the intended
concurrency and containment properties.

## 6. Lifecycle, recovery, and cleanup

Use the generic managed-process implementation. It must:

1. Track the complete child process tree, not only the bridge pid.
2. Support cancellation, timeout, normal completion, startup failure, and
   unexpected death with truthful terminal states.
3. Clean request-local state idempotently; quarantine it when deletion is unsafe.
4. Persist enough evidence to diagnose a stranded or requeued record after a
   gateway restart.
5. Publish terminal lifecycle events, including interrupted terminals, so
   downstream jobs do not wait forever.

Recovery must reconcile the admission index, active-work index, queue records,
and process evidence transactionally. “Requeued” records need an explicit
recovery outcome and must not remain stranded as apparent active work.

## 7. Gateway profiles and reload

Profile resolution follows this precedence:

1. explicit `agent-profile-id`;
2. explicit provider/model;
3. gateway default profile.

The gateway should load profiles into a versioned registry and give each request
an immutable profile snapshot. Live reload must atomically publish a new
generation for future requests while existing sessions retain their snapshot.
Invalid reloads must leave the last valid generation active and emit an
observable configuration error.

## 8. Observability contract

Expose, at minimum:

- queued, starting, running, waiting, completed, failed, cancelled, timed out,
  interrupted, and recovery states;
- provider, model, profile generation, session id, request id, cwd, and runtime
  fingerprint;
- launch command metadata and process evidence with secrets redacted;
- ACP progress and terminal events through the same wait/status surface;
- explicit premature-halt, repetition, and missing-terminal detection where the
  protocol permits it.

Every request must be diagnosable without opening the agent's private state.
The gateway's event stream is the source of truth for callers and downstream
jobs.

## 9. Required validation

The harness is ready only when these tests pass:

- descriptor resolution selects the provider and execution adapter;
- clean managed provisioning installs every pinned dependency;
- launch uses the managed executable, requested cwd, model, and session path;
- two concurrent requests receive distinct request-local state directories;
- shared project files are documented and behave as expected;
- ACP progress, completion, failure, cancellation, timeout, and interruption
  are projected correctly;
- child-tree cleanup succeeds after normal and abnormal termination;
- restart/recovery reconciles active work and publishes terminal outcomes;
- malformed provider or MCP configuration fails diagnostically without
  corrupting the active registry;
- Docker end-to-end tests exercise the real internal model-loading rig.

Run focused unit tests first, then the Docker suite. A green adapter unit test
does not prove gateway readiness.

## 10. Pi implementation checklist

Pi's current implementation should be checked against this list:

- `src/audiagentic/components/providers/adapters/pi/acp.py` resolves managed
  `pi-acp` and forwards cwd, model, session directory, and request environment.
- `src/audiagentic/runtime/harness/context.py` creates the unique launch root;
  gateway session dispatch owns request cleanup and quarantine policy.
- `src/audiagentic/config/provisioning/harness/pi.yaml` pins Pi, MCP adapter,
  and ACP bridge versions.
- `src/audiagentic/config/providers/pi.yaml` contains both the declared
  isolation tier and the executable registration required by the gateway.
- `docs/reference/PROVIDER_CAPABILITY_REFERENCE/harnesses/profiles/pi.md`
  remains aligned with tested ACP and isolation capabilities.

Pi's descriptor now contains the required one-shot execution block and its live
session path is provider-owned ACP composition. A future harness that omits its
execution registration must fail at descriptor/execution resolution with
`VAL-EXEC-002`; that is an integration defect, not evidence that its bridge is
broken.

## Definition of done

A harness is gateway-ready when provisioning, descriptor registration, launch,
request-local state, process lifecycle, observability, recovery, profile
reload, and Docker validation are all complete, reviewed against the reusable
AS/SH ownership boundaries, and backed by a release-ledger event.
