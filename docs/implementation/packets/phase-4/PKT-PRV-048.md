# PKT-PRV-048 — shared provider live-stream capture contract + harness

**Phase:** Phase 4.9
**Status:** DEFERRED_DRAFT
**Primary owner group:** Shared provider capture

## Purpose

Create the shared capture harness that records provider progress, mirrors live output to the
console, and persists normalized runtime event records without moving persistence into the
provider.

## Scope

- shared live-stream event contract
- stdout/stderr capture helpers
- normalized runtime event writer
- console mirroring switches
- runtime output layout

## Dependencies

- PKT-PRV-031 verified
- PKT-PRV-032 verified
- PKT-PRV-033 verified
- PKT-PRV-037 verified
- PKT-PRV-038 verified

## Not in scope

- Discord overlay implementation
- provider-native business logic
- job control semantics
- install/bootstrap orchestration

## Files likely to change

- `src/audiagentic/jobs/stream_capture.py`
- `src/audiagentic/jobs/prompt_trigger_bridge.py`
- `src/audiagentic/jobs/prompt_launch.py`
- `src/audiagentic/providers/execution.py`
- `docs/schemas/provider-stream-event.schema.json`
- `docs/schemas/provider-stream-manifest.schema.json`
- tests for stream capture and console mirroring

## Implementation sequence

1. Define the normalized stream event contract.
2. Add shared capture helpers for stdout/stderr and event records.
3. Add runtime file paths and persistence rules.
4. Add console mirroring toggles.
5. Add tests that validate capture without breaking existing launch behavior.

## Acceptance criteria

- live stream capture can be enabled and disabled cleanly
- runtime artifacts contain deterministic progress records
- console mirroring does not change final launch behavior
- the harness is reusable by Cline and Codex first
