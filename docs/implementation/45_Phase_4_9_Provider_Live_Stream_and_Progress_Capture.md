# Phase 4.9 - Provider Live Stream and Progress Capture

## Purpose

Implement the shared live-output capture layer that records provider progress, mirrors it to
the console, and persists runtime artifacts for later consumption by overlays such as
Discord.

This phase is about **AUDiaGentic-owned capture and rendering**, not provider-owned
persistence.

## What this phase leaves behind

- a shared live-stream capture contract
- normalized progress event records
- raw stdout/stderr capture for provider tasks
- console mirroring switches for operator visibility
- a stable data path that Discord can subscribe to later
- first-wave provider guidance for Cline and Codex

## Scope

### Shared work

- define the live-stream event format
- define runtime file layout for captured output
- add shared capture helpers for stdout/stderr and normalized progress events
- add CLI/bridge flags for live streaming
- add tests for stream capture and final artifact persistence

### Provider first run

The first implementation pass should target:
- Cline
- Codex

Those two providers already have stable CLI execution paths and can prove the stream contract
before the broader provider set is enabled.

## Runtime outputs

Recommended runtime files per job:

```text
.audiagentic/runtime/jobs/<job-id>/events.ndjson
.audiagentic/runtime/jobs/<job-id>/stdout.log
.audiagentic/runtime/jobs/<job-id>/stderr.log
```

Final artifacts remain provider-specific:
- review jobs still write `review-report.*.json`
- review bundles still write `review-bundle.json`
- implementation jobs still write the existing job/stage artifacts

## Implementation steps

1. Add a shared stream capture helper.
2. Add a normalized progress event writer.
3. Teach the prompt-trigger bridges to run in streaming mode.
4. Capture Cline progress first because it already emits structured live events.
5. Capture Codex progress second using the same shared stream contract.
6. Validate that final structured artifacts still write correctly after the live capture run.
7. Document the stream contract in the provider specs and current-state summary.

## Acceptance criteria

- Cline can run with live console output and normalized runtime capture.
- Codex can run with live console output and normalized runtime capture.
- The same job still produces its final structured artifact.
- The stream contract can later be consumed by Discord without changing provider adapters.

## Packet set

- `PKT-PRV-048` - shared live-stream capture contract and harness
- `PKT-PRV-049` - Codex live-stream capture integration
- `PKT-PRV-050` - Cline live-stream capture integration

## Notes

- This phase does not replace Phase 4.6 prompt-trigger launch behavior.
- This phase does not require provider execution semantics to change.
- This phase does not make Discord a dependency of the core runtime.
