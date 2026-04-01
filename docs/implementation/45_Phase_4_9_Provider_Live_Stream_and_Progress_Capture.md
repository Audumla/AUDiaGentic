# Phase 4.9 - Provider Live Stream and Progress Capture

## Purpose

Implement the shared live-output capture layer that records provider progress, mirrors it to
the console, and persists runtime artifacts for later consumption by overlays such as Discord.

This phase is about **AUDiaGentic-owned capture and rendering**, not provider-owned
persistence.

## What this phase leaves behind

- a shared live-stream capture contract
- normalized progress event records once the writer is in place
- raw stdout/stderr capture for provider tasks
- console mirroring switches for operator visibility
- a stable data path that Discord can subscribe to later
- first-wave provider guidance for Cline and Codex

## Scope

### Shared work

- define the live-stream event format
- define runtime file layout for captured output
- add shared capture helpers for stdout/stderr and raw runtime logs first
- layer in normalized progress-event writing when the stream writer exists
- add CLI/bridge flags for live streaming
- add tests for stream capture and final artifact persistence
- keep console teeing resilient so encoding/rendering issues cannot crash a successful provider run

### Provider first run

The first implementation pass should target:
- Cline
- Codex

Those two providers already have stable CLI execution paths and can prove the stream capture
contract before the broader provider set is enabled.

## Runtime outputs

Recommended runtime files per job:

```text
.audiagentic/runtime/jobs/<job-id>/events.ndjson
.audiagentic/runtime/jobs/<job-id>/stdout.log
.audiagentic/runtime/jobs/<job-id>/stderr.log
```

At the current implementation stage, the bridge can tee stdout/stderr and preserve raw logs.
The normalized `events.ndjson` stream is the target shape for the shared writer and should be
treated as the canonical stream record once the writer is wired in.

Final artifacts remain provider-specific:
- review jobs still write `review-report.*.json`
- review bundles still write `review-bundle.json`
- implementation jobs still write the existing job/stage artifacts

## Shared implementation responsibilities

The shared harness for this phase owns:

- process stdout/stderr reading
- console mirroring policy
- durable raw log persistence
- normalized event writing when enabled
- omission/redaction of non-log-safe material

Provider-specific integrations own only:

- event extraction logic for that provider's raw output
- mapping provider-native event families into canonical event kinds
- provider-specific smoke tests proving the shared harness works for that provider

## Recommended first-pass implementation order

1. harden the shared streaming helper so console encoding issues cannot fail a successful job
2. add `events.ndjson` writer support to the shared harness
3. implement Cline event extraction because it already emits rich NDJSON
4. implement Codex wrapper-milestone event emission
5. add normalized event fixtures and provider-specific integration tests
6. update provider matrices/specs only after the shared writer and first-wave extractions are stable

## Detailed implementation steps

1. Add or harden the shared stream capture helper.
2. Add a normalized progress event writer.
3. Teach the prompt-trigger bridges to run in streaming mode.
4. Capture Cline progress first because it already emits useful live CLI output.
5. Capture Codex progress second using the same shared stream contract.
6. Validate that final structured artifacts still write correctly after the live capture run.
7. Document the stream contract in the provider specs and current-state summary.

## Tests to add

- shared streaming helper writes `stdout.log` and `stderr.log`
- shared streaming helper does not crash on non-UTF-8 console output
- shared writer appends canonical `events.ndjson` records
- Cline integration emits canonical event kinds from native NDJSON
- Codex integration emits canonical wrapper milestone events
- final review/job artifacts still persist after a streamed run

## Acceptance criteria

- Cline can run with live console output and raw runtime capture, with normalized progress records available once the shared writer is wired in
- Codex can run with live console output and raw runtime capture, with normalized progress records available once the shared writer is wired in
- the same job still produces its final structured artifact
- the stream contract can later be consumed by Discord without changing provider adapters
- console teeing cannot crash the job on Windows or other non-UTF-8 default consoles
- the shared harness, not the provider adapter, owns durable stream artifact layout

## Packet set

- `PKT-PRV-048` - shared live-stream capture contract and harness
- `PKT-PRV-049` - Codex live-stream capture integration
- `PKT-PRV-050` - Cline live-stream capture integration

## Notes

- This phase does not replace Phase 4.6 prompt-trigger launch behavior.
- This phase does not require provider execution semantics to change.
- This phase does not make Discord a dependency of the core runtime.
- later providers should only be added after the first-wave shared event writer is stable
