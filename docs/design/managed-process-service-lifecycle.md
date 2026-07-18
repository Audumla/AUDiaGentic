# Managed process and service lifecycle contract

Status: PR05 contract, version 1. This document defines the smallest shared
foundation seam required by the gateway, embedded rig, and detached agent
sessions. PR06 implements durable service state and leases; PR07 implements
process-backed start-or-attach and guarded shutdown.

## 1. Reuse doctrine

The implementation extends existing foundation capabilities:

| Concern | Existing authority | Required extension |
|---|---|---|
| Machine/project paths | `foundation.paths` | one managed-service runtime path helper |
| Atomic records | `foundation.io.atomic_write_json` | strict service/lease loaders and revision checks |
| Cross-process mutation | `foundation.system.process.StartupLock` | one lock per service identity |
| State legality | `foundation.workflow.TransitionEngine` | managed-service transition configuration |
| PID/process operations | `foundation.system.process` | ownership proof verification before stop/adopt |
| Supervised children | `foundation.system.supervised_process` | no change in PR05/PR06 |
| Durable diagnostics | foundation operational records and timelines | neutral service facts only |
| Notifications | foundation event bus | optional post-commit facts; never state authority |

No second path resolver, state machine, event bus, lock implementation,
registry utility, journal format, or process-tree killer is introduced.

## 2. ManagedProcess

`ManagedProcess` is an evidence record for a process relationship. It is not a
subprocess wrapper or universal command runner.

Scopes:

- `supervised-child`: caller-owned foreground process; cannot outlive caller.
- `session-child`: caller-owned live session process; closes with its session.
- `detached-owner`: owned process intentionally detached from its starter.
- `shared-service-host`: detached process serving independently leased clients.
- `external-adopted`: externally launched process; observation is allowed, but
  termination requires explicit adoption proof.

The durable process evidence contains only: PID, OS-observed creation/start
identity when available, redacted command fingerprint, cwd fingerprint,
owner epoch, scope, optional group/job identity, and ownership-proof kind. Raw
argv, environment, stdout/stderr, credentials, and auth tokens are forbidden.

Liveness is not ownership. A destructive operation requires a current PID plus
at least one non-PID proof that matches the record: creation identity, command
fingerprint, endpoint identity handshake, owned process-group/job evidence, or
lock-held launch/adoption proof. PID-only or image-name reaping is prohibited.

## 3. ManagedService identity and state

A service key is `(service_kind, service_id, scope)`. Names are domain-neutral;
consumer-specific behavior remains in the consumer. `scope` is `machine` in v1;
project identity stays in gateway request manifests, not service discovery.

States and legal transitions:

| State | Legal targets |
|---|---|
| `starting` | `running`, `failed`, `stopping` |
| `running` | `draining`, `failed`, `stopping` |
| `draining` | `running`, `stopping`, `failed` |
| `stopping` | `stopped`, `failed` |
| `stopped` | `starting` |
| `failed` | `starting`, `stopping`, `stopped` |

Every mutation occurs under the service's `StartupLock`, reads the current
record, writes via `atomic_write_json`, and only then emits best-effort
diagnostics. Lifecycle transitions validate revision and owner epoch.
Heartbeat refreshes validate the owner epoch only, so unrelated lease revision
changes cannot create spurious owner conflicts. Events and external health
probes do not mutate records.

The v1 record contains:

- contract version, service key, state, revision, owner epoch, timestamps;
- `ManagedProcess` evidence when a process exists;
- endpoint protocol/address plus an opaque authentication-reference identifier;
- protocol/capability version needed for compatibility checks;
- redacted readiness/heartbeat facts and last failure classification;
- no project request/session contents and no credentials or raw process output.

## 4. Client leases

A lease is a process-level dependency on a service, not a session turn or GPU
slot. It contains lease id, client instance id, service key, owner epoch,
acquired/renewed/expires timestamps, and optional opaque correlation id.

Acquire, renew, release, and expiry cleanup use the same per-service lock and
atomic revision update as service transitions. An expired lease is inactive but
remains observable until bounded cleanup. A stale client cannot renew a lease
from an earlier owner epoch.

Lease count alone never authorizes stop. PR07 must re-check, under the same
lock, that there are no active leases, the consumer reports quiescence, the
owner epoch is unchanged, and process ownership proof still matches.

## 5. Consumer boundary

Foundation owns records, transitions, leases, liveness/ownership verification,
and generic start/attach/drain/stop coordination. A consumer supplies typed
launch declaration, endpoint health/identity handshake, authorization check,
quiescence check, and domain shutdown request. Consumer callbacks are passed or
registered through a typed composition-root seam; durable records never contain
dotted callables or requester policy.

The gateway owns request/session state and authentication semantics. The rig
owns model readiness. Agent sessions own turn/session quiescence. None may
create a parallel service record, PID registry, lease counter, or reaper.

### 5.1 Bounded start and Windows lifetime evidence

`start_or_attach` serializes launch and readiness publication under the
per-service lock. The declared readiness timeout plus a one-second scheduling
margin must fit within the store's lock timeout; invalid combinations fail with
`VAL-MSVC-037` before launch. This makes the lock-hold bound explicit and lets
concurrent attachers wait within the same declared budget.

On Windows, a fully detached owner requests Job Object breakaway. If the
supervising job denies breakaway, foundation retries without that flag and
publishes the process scope as `session-child`, with a warning. This is an
observable degraded lifetime: the process may die when the supervising job
closes and must never be represented as `shared-service-host`. Consumers that
require survival beyond the supervisor reject that scope; consumers may opt to
use it while the supervisor remains alive. POSIX and fully detached Windows
children are reaped asynchronously after exit so the starter does not retain a
zombie or process handle.

## 6. Planned narrow APIs

PR06:

- `ManagedServiceStore(root)` with `read`, `create`, `transition` and lease
  acquire/renew/release/expire operations;
- immutable typed records returned at the public boundary;
- injected clock/PID probes for deterministic Windows/POSIX tests.

PR07:

- `start_or_attach(declaration, hooks)`;
- `request_drain(service_key)` and `stop_if_quiescent(service_key, hooks)`;
- explicit safe degraded outcomes when ownership cannot be proven.

No MCP tools, remote transport, scheduler, retry framework, or component-domain
callback vocabulary belongs in foundation.

## 7. Durable layout and observability

The machine-scoped default is resolved by foundation paths beneath
`AUDIAGENTIC_HOME`/`~/.audiagentic`, not by consumer literals:

```text
services/<scope>/<service-kind>/<service-id>/
  service.json
  start.lock
  timeline.ndjson
```

The service JSON atomically contains the bounded lease records and is
authoritative. Timeline/operational records are
redacted observations and may be rebuilt or truncated by later retention work.
The in-process event bus may publish neutral post-commit lifecycle facts but is
not used for discovery, locking, or recovery.

## 8. Non-goals

- generic workflow or distributed consensus engine;
- remote RPC/service framework;
- agent-group, GPU, queue, or request scheduling;
- automatic restart policy or unbounded retry;
- secrets store or token transport;
- migration of existing consumers in PR05;
- process termination without verified ownership.
