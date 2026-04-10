# PKT-PRV-074 — Shared streaming hardening and observability seam

**Phase:** Phase 4.9.1
**Status:** READY_TO_START
**Owner:** Infrastructure

## Objective

Harden the shared streaming harness after the baseline 4.9 implementation by adding
configuration-driven timeout support, observable sink failures, and validation of
stream-controls input without changing provider-specific extractor ownership.

## Shared config contract

The hardening work in Phase 4.9.1 must stay configuration-driven. The shared contract should
live under `stream-controls` in the normalized packet/runtime request shape so provider jobs,
tests, and future operator defaults all read the same keys.

Config sources and precedence:

- project defaults live in `.audiagentic/project.yaml` under `prompt-launch.default-stream-controls`
- provider overrides may live in `.audiagentic/providers.yaml` under `providers.<provider-id>.stream-controls`
- request-time overrides live in the normalized launch request under `stream-controls`
- precedence is: request `stream-controls` -> provider `stream-controls` -> project `default-stream-controls`

Required keys for the shared contract:

- `timeout-seconds` - optional hard timeout for the full streamed subprocess run; unset means no
  hard timeout
- `timeout-warning-seconds` - optional warning threshold that records a diagnostic without
  terminating the process
- `sink-error-policy` - one of `warn` or `fail`; default `warn`
- `control-validation-policy` - one of `normalize`, `warn`, or `fail`; default `normalize`
- `termination-policy` - one of `graceful-kill` or `warn-only`; default `warn-only` unless an
  explicit hard timeout is configured

The docs and implementation must keep these policies configurable rather than embedding
short-job assumptions in code. Long-running providers remain valid.

## Scope

- add configuration-driven timeout handling to `run_streaming_command(...)`
- define sink-failure observability policy so sink exceptions remain non-fatal but visible
- validate `stream_controls` before sink construction
- document error-propagation expectations for process failures versus sink failures
- define warning-first versus hard-enforcement behavior in config rather than code constants
- define the concrete `stream-controls` keys and defaults used by the shared hardening layer

## Not in scope

- provider-specific extraction logic
- network-stream features such as authentication, compression, or backpressure
- retry logic, rate limiting, or monitoring systems

## Files likely to change

- `src/audiagentic/streaming/provider_streaming.py`
- `src/audiagentic/streaming/sinks.py`
- streaming tests
- Phase 4.9 docs

## Timeout semantics

The timeout contract must distinguish warnings from enforcement:

- `timeout-warning-seconds` crossing emits a runtime diagnostic or warning event but keeps the
  process alive
- `timeout-seconds` crossing only terminates the process when a hard timeout is actually set
- if termination occurs, the implementation must record that the run ended by configured timeout
  rather than ordinary provider completion
- warning-only mode is valid for long-running providers and should remain the default posture

## Acceptance criteria

- streaming runs can honor a configured timeout or warning threshold
- sink failures remain isolated but are surfaced through an observable diagnostic path
- invalid stream-control input is rejected or normalized deterministically according to
  `control-validation-policy`
- warning-first behavior is the default unless strict enforcement is explicitly configured
- timeout behavior, sink failure behavior, and control validation behavior are driven by the
  documented `stream-controls` keys rather than hardcoded constants
- provider-specific extractor packets do not need to re-own shared streaming hardening
