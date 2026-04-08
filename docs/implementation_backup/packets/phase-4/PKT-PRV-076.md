# PKT-PRV-076 — Bounded capture and truncation policy

**Phase:** Phase 4.9.1
**Status:** READY_TO_START
**Owner:** Infrastructure

## Objective

Prevent unbounded memory growth in the shared streaming harness by adding a configuration-driven
bounded capture policy for in-memory stream accumulation and a documented truncation/overflow
behavior.

## Shared config contract

`PKT-PRV-076` should extend the shared `stream-controls` contract with bounded-capture keys:

- `in-memory-max-bytes` - optional byte cap for captured stdout/stderr; unset means unbounded
- `overflow-policy` - one of `warn-only`, `truncate-head`, `truncate-tail`, or `fail`; default
  `warn-only`
- `overflow-marker-text` - optional marker inserted when truncation occurs; default should be a
  managed AUDiaGentic marker
- `large-output-warning-bytes` - optional warning threshold below the hard cap

Limits must remain operator-configurable because some providers legitimately emit long outputs.

## Scope

- add configuration-driven bounds for in-memory stream capture
- define truncation or overflow markers for oversized captures
- document how bounded capture affects returned `stdout` / `stderr`
- add tests for large-output behavior
- allow operators to opt into large limits for providers that legitimately emit long responses
- define whether truncation retains the head, tail, or full warning-only capture semantics

## Not in scope

- provider-specific output parsing
- compression or archival policies

## Bounded-capture semantics

The packet must define deterministic output semantics:

- `warn-only` records a diagnostic but keeps full capture when no hard cap is set
- `truncate-head` keeps the newest tail region and inserts the overflow marker
- `truncate-tail` keeps the earliest head region and inserts the overflow marker
- `fail` is opt-in and should only trigger when explicitly configured

The implementation must state whether the byte limit applies independently to stdout and stderr;
the default assumption should be independent per-stream limits.

## Acceptance criteria

- in-memory capture no longer grows without bound when a cap is configured
- truncated captures remain explicit and diagnosable
- downstream callers receive deterministic behavior when output exceeds limits
- limits are configurable and do not assume short responses by default
- the packet documents concrete `stream-controls` keys, defaults, and overflow modes
- tests prove bounded capture behavior for both stdout and stderr independently
