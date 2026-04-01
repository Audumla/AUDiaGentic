# Phase 4.10 - Provider Live Input and Interactive Session Control

## Purpose

Implement the shared interactive-input layer that lets AUDiaGentic send follow-up input into a
live provider session while keeping session control and persistence owned by AUDiaGentic.

This phase is about **AUDiaGentic-owned session control**, not provider-owned persistence.

## What this phase leaves behind

- a shared live-input and interactive-session control contract
- normalized session-input event records once a live-session manager is attached
- raw input capture for provider tasks
- console input and operator control switches
- a stable data path that Discord can subscribe to later
- first-wave provider guidance for Cline and Codex
- a follow-on secure-session-reference seam so sensitive provider session keys do not need to be written into durable runtime logs

## Scope

### Shared work

- define the live-input event format
- define runtime file layout for captured input
- add shared capture helpers for session input and raw runtime logs first
- layer in normalized input-event writing when the session manager exists
- add CLI/bridge flags for interactive sessions
- add tests for input capture and final artifact persistence

### Provider first run

The first implementation pass should target:
- Cline
- Codex

Those two providers already have stable CLI execution paths and can prove the session-input
capture contract before the broader provider set is enabled.

## Runtime outputs

Recommended runtime files per job:

```text
.audiagentic/runtime/jobs/<job-id>/input.ndjson
.audiagentic/runtime/jobs/<job-id>/stdin.log
.audiagentic/runtime/jobs/<job-id>/input-events.ndjson
```

At the current implementation stage, the harness records and persists session input and raw
logs. A true mid-run provider attachment layer is the later step that will make those records
drive a live session.

Final artifacts remain provider-specific:
- review jobs still write `review-report.*.json`
- review bundles still write `review-bundle.json`
- implementation jobs still write the existing job/stage artifacts

## Implementation steps

1. Add a shared session-input capture helper.
2. Add a normalized input event writer.
3. Teach the prompt-trigger bridges and session-input CLI to persist controlled input records.
4. Capture Cline interactive turns first because its CLI behavior already exposes useful input
   capture behavior.
5. Capture Codex interactive turns second using the same shared session-input contract.
6. Validate that final structured artifacts still write correctly after interactive turns.
7. Reserve a secure-session-reference seam so raw provider session keys are not treated as log-safe.
8. Document the session-input contract in the provider specs and current-state summary.

## Acceptance criteria

- Cline can receive recorded interactive input and raw runtime capture, with normalized input records available once the session manager is wired in.
- Codex can receive recorded interactive input and raw runtime capture, with normalized input records available once the session manager is wired in.
- The same job still produces its final structured artifact.
- The session-input contract can later be consumed by Discord without changing provider adapters.
- Full mid-run interactive control requires a provider adapter or future session manager that can attach new input to a live process; the persistence harness alone is not sufficient for that guarantee.

## Packet set

- `PKT-PRV-051` - shared live-input capture contract and harness
- `PKT-PRV-052` - Codex live-input capture integration
- `PKT-PRV-053` - Cline live-input capture integration
- `PKT-PRV-054` - session provenance redaction and secure-session reference seam

## Notes

- This phase does not replace Phase 4.6 prompt-trigger launch behavior.
- This phase does not replace Phase 4.9 live-stream capture.
- This phase does not require provider execution semantics to change.
- This phase does not make Discord a dependency of the core runtime.
