# PKT-PRV-075 — Normalized event writer hardening

**Phase:** Phase 4.9.1
**Status:** READY_TO_START
**Owner:** Infrastructure

## Objective

Harden `events.ndjson` writing so normalized stream records are validated and appended through a
coordinated write policy rather than relying on unsynchronized best-effort file appends.

## Shared config contract

`PKT-PRV-075` should extend the shared `stream-controls` contract introduced by `PKT-PRV-074`
with event-writer-specific policy keys:

- `invalid-event-policy` - one of `warn`, `quarantine`, or `fail`; default `quarantine`
- `event-write-policy` - one of `locked-append` or `single-writer`; default `locked-append`
- `event-quarantine-path` - optional runtime-relative path override; default should remain under
  `.audiagentic/runtime/jobs/<job-id>/events.invalid.ndjson`
- `event-schema-validation` - boolean; default `true`

## Scope

- validate normalized stream-event payloads against the canonical schema before write
- define and implement a coordinated append policy for `events.ndjson`
- add tests for malformed-event rejection and concurrent append safety
- define policy-controlled handling for invalid event records: reject, warn, or quarantine
- define where quarantined invalid event records are written when quarantine mode is enabled

## Not in scope

- provider-specific extraction logic
- event transport beyond local runtime artifacts

## Invalid-event handling

The packet must define deterministic behavior for each invalid-event mode:

- `warn` - emit a diagnostic and skip the malformed canonical event
- `quarantine` - emit a diagnostic and write the rejected payload to the quarantine artifact
  instead of `events.ndjson`
- `fail` - raise the writer-side error defined by the shared policy and terminate the event-write
  path explicitly

`events.ndjson` must remain canonical-only; quarantined payloads must never be appended there.

## Acceptance criteria

- malformed normalized event payloads are rejected before they reach `events.ndjson`
- `events.ndjson` writes use a single-writer or equivalent coordinated append policy
- shared tests prove the event writer remains valid under concurrent stdout/stderr activity
- invalid event handling is policy-driven rather than hardcoded
- quarantine mode writes rejected payloads to a deterministic runtime artifact outside the
  canonical `events.ndjson` stream
- the packet documents the concrete `stream-controls` keys used by the event writer
