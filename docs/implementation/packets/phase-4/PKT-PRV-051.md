# PKT-PRV-051 — shared provider live-input capture contract + harness

**Phase:** Phase 4.10
**Status:** READY_FOR_REVIEW
**Primary owner group:** Shared provider input/session control

## Purpose

Create the shared session-input harness that records follow-up input, mirrors control changes to
the console if needed, and persists normalized runtime input records without moving session
persistence into the provider.

## Scope

- shared live-input event contract
- stdin/input forwarding helpers
- normalized runtime input writer
- console input and pause/resume switches
- runtime input layout
- shared harness implementation and test coverage

## Dependencies

- PKT-PRV-048 deferred draft or better
- PKT-PRV-031 verified
- PKT-PRV-032 verified
- PKT-PRV-037 verified

## Not in scope

- Discord overlay implementation
- provider-native business logic
- job control semantics
- install/bootstrap orchestration

## Files likely to change

- `src/audiagentic/jobs/session_input.py`
- `src/audiagentic/jobs/prompt_trigger_bridge.py`
- `src/audiagentic/jobs/prompt_launch.py`
- `src/audiagentic/providers/execution.py`
- `docs/schemas/provider-session-input.schema.json`
- `docs/schemas/provider-session-manifest.schema.json`
- tests for session-input capture and console forwarding

## Implementation sequence

1. Define the normalized session-input event contract.
2. Add shared capture helpers for operator input and event records.
3. Add runtime file paths and persistence rules.
4. Add console input toggles.
5. Add tests that validate capture without breaking existing launch behavior.

## Acceptance criteria

- live interactive input can be enabled and disabled cleanly
- runtime artifacts contain deterministic session-input records
- console input does not change final launch behavior
- the harness is reusable by Cline and Codex first
