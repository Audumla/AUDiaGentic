# Architecture Implementation Guidelines

This document contains assessed implementation guidance extracted from
`ARCHITECTURE_STANDARDS.md`. It supports the architectural invariants in that
document, but concrete class names, paths, schemas, and test implementations
may evolve without changing the architecture standard.

## 1. Extension Registries

Use a registry only for a genuine extension point. The owner defines its typed
protocol and key namespace; callers use that protocol and receive typed results.
Registration, replacement, lifetime, duplicate-key handling, and unknown-key
failure must be deterministic and tested.

Do not use a service locator, an arbitrary `dict[str, Callable]`, a string or
dotted-path lookup, or requester-owned handler names to conceal a forbidden
dependency. Use a direct allowed import, a typed event, or composition-root
wiring instead.

## 2. MCP Servers and Metadata

- Construct component servers through `mcp_server(__name__)` and run them via
  `run_mcp_server(server_factory, label)`.
- Server instructions, tool descriptions, and parameter descriptions are
  configuration-owned MCP metadata. Python reads them through the metadata
  helpers; it does not embed user-facing literals.
- A tool may omit optional metadata only when the metadata contract marks it
  optional. Auto-generated descriptions are a migration fallback, not a second
  production authority.
- Component configuration defines `instructions` and `tool-descriptions`.
  A tool description can be a string or an object with `description` and
  `parameters`; component-owned extension keys may pass through unchanged.
- Keep tools as protocol translation only. Resolve project/caller context and
  apply transport-only timeout, progress, and logging behavior here, then call
  the owning framework-neutral public API. Validation, persistence,
  orchestration, retries, and lifecycle belong behind that API so CLI, events,
  services, and tests reuse the same behavior.

## 3. Error, Logging, and Redaction Practice

- Register each public `AudiaGenticError` code in the owning component's
  `config/components/<component>/error-resolutions.yaml` before use.
- At process, remote-service, subprocess, and event-handler boundaries, log or
  normalize unexpected failures with safe context. Local expected recovery does
  not require noisy logging.
- Use `logger = logging.getLogger(__name__)`; libraries do not call `print()`.
  Log entity context with structured `extra` fields. Never log MCP tool args.
- Redact captured stdout/stderr before putting it in a result, error, timeline,
  sidecar record, or log. Use the shared redaction implementation; do not create
  local pattern lists.
- Credentials may traverse only the minimum trusted transport path required for
  authentication. They never appear in application-visible results, logs,
  errors, persistence, telemetry, or dead-letter records.

## 4. External-Service Failures

Classify a remote failure as `transient`, `configuration`, `authorization`, or
`contract`.

| Class | Retry | Degradation |
|---|---|---|
| `transient` | At most one bounded retry, only when operation is idempotent | Last-known-good cache when available |
| `configuration` | Never | None |
| `authorization` | Never | None |
| `contract` | Never | None |

Respect server retry guidance where available. Never use unbounded backoff or
sleep-loop polling. Best-effort background work may return a safe degraded
result; include `failure_class`, `fallback`, `stale`, `stale_age` when known,
`action_needed`, and the canonical `error_code`. See
[Observability Standards](OBSERVABILITY_STANDARDS.md) for durable reporting.

## 5. Schema and Event Contracts

- A component-owned schema is authoritative. A matching foundation mirror is
  byte-identical and read-only; component-only schemas have no foundation
  mirror. Exact locations and registry loading are defined by the schema
  implementation and its tests.
- Every published bus topic is declared by its sole owning component before use.
  Use an owner-exported module constant rather than an inline literal or dynamic
  expression.
- Topic declarations define required and optional payload fields. Add a full
  schema only when a consumer needs strict payload validation.
- The component event registry is at
  `src/audiagentic/config/components/<component>/events.yaml`. Its loader and
  conformance tests enforce ownership, overlays, and naming.

## 6. Async Failure Handling

Event handlers catch boundary exceptions, write a redacted durable dead-letter
record, and allow dispatch to continue. Automatic replay is prohibited unless
the component defines and tests an idempotency key or guard. Manual replay must
recover safe inputs and redispatch through the owning component.

Dead-letter storage, record shape, and retention are component contracts. The
agent-jobs implementation currently uses `write_dead_letter` and
`append_operational_record`; treat those as implementation APIs, not universal
architecture primitives.

## 7. Writing External Artifacts

For a shared or user-owned file, use the established owner and writer for that
artifact. It must identify ownership, preserve user content, write atomically
where feasible, and support safe adoption, pruning, and dry-run/status behaviour
when those operations exist. Format adapters parse and render; they do not create
parallel ownership systems.

A narrowly scoped adapter exception is acceptable only for a dynamically
discovered third-party artifact that existing mechanisms cannot represent. It
needs preservation and failure tests plus a documented reason.

## 8. Lazy Initialization and Discovery

- Prefer on-first-access loading for expensive registries, dependencies, and
  shared state.
- Public accessors return ready values; they do not expose priming or load-state
  APIs.
- Loaders are idempotent and cached. Prefer shared lazy-loader support to
  component-local guards.
- Pluggable modules use descriptor/config or package discovery rather than a
  manually maintained import list or `__all__`.
- Generated assets register an owned renderer or virtual-asset contribution;
  runtime iterates contributions rather than branching on output paths.

## 9. Migration Validation

For a move, rename, or deletion, search production code, tests, configuration,
decorators, dynamic imports, patches, and dotted-path strings for the old path.
Update all callers and remove obsolete compatibility paths in the same change.
Do not add an alias, shim, dual route, fallback, or compatibility test unless an
approved external obligation is recorded first. Run relevant unit, integration,
contract, and architecture checks; state exact validation scope in the change
record.

## 10. Provider Platform API

`providers` is the current approved platform API in the architecture standards.
Its permitted callers use only
`audiagentic.components.providers.providers_api`; they must not import provider
adapters, services, serializers, capability configuration, matrices, registries,
or handlers. Runtime automation becomes executable only through explicit
composition-root registration; descriptive provider configuration is not
execution authority.

Provider automation recipes share one internal declarative recipe-definition
schema and private lifecycle contract. Public functions, payloads, and results
remain family-specific. Resource management and agent execution do not become
recipes. Schema validation never substitutes for explicit code registration.

Classify provider API entries by mutation ownership: queries do not mutate;
resource commands mutate AUDiaGentic-owned desired state or cache; automation
mutates external provider state or owned contributions in provider files;
execution runs agent work. Invoking provider-specific code alone does not make
a query or resource command automation.

Provider-specific request/result types remain in providers when they contain
provider concepts. Put a type in foundation only when it is domain-neutral and
independently consumed outside provider management.
