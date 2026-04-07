# PKT-PRV-049 — Codex live-stream capture integration

**Phase:** Phase 4.9
**Status:** READY_TO_START
**Primary owner group:** Codex

## Purpose

Wire the Codex prompt-trigger path into the Phase 4.9 generic sink harness so live output is
captured, mirrored, and normalized without Codex owning any persistence logic.

## Scope

- register `RawLogSink` and `NormalizedEventSink` for Codex bridge runs
- add a `CodexEventExtractor` sink that parses Codex wrapper milestone lines into canonical
  stream events before forwarding to `NormalizedEventSink`
- wire `ConsoleSink` for live console mirroring during Codex runs
- make `src/audiagentic/execution/providers/adapters/codex.py` the Codex-owned home of
  provider-specific stream extraction, sink wiring helpers, and any Codex-only parsing needed
  for this packet
- preserve final structured output after the run
- keep bridge behavior unchanged when streaming is disabled (no sinks registered)

## Codex-specific extraction

Codex emits structured milestone lines in its wrapper output.  A `CodexEventExtractor` sink
should translate these into canonical `provider-stream-event` records (task-start,
task-progress, completion) before they reach `NormalizedEventSink`.  This extractor is
Codex-owned and does not belong in the shared harness.

## Dependencies

- PKT-PRV-048 implemented (sink interface + built-in sinks available)
- PKT-PRV-032 verified
- Codex CLI path available

## Not in scope

- Codex execution semantics rewrite
- provider model catalog changes
- prompt syntax changes
- shared harness modifications

## Files likely to change

- `tools/codex_prompt_trigger_bridge.py` — register sinks before launch
- `src/audiagentic/execution/providers/adapters/codex.py` — `CodexEventExtractor` sink
- Codex-focused streaming tests and fixtures
- tests for Codex stream capture and extractor

## Ownership boundary

This packet owns Codex-specific changes in `src/audiagentic/execution/providers/adapters/codex.py`
and the Codex bridge registration seam. Shared sink primitives, sink protocols, and generic
runtime persistence remain owned by `PKT-PRV-048`.

## Acceptance criteria

- Codex runs with live output visible in the console via `ConsoleSink`
- AUDiaGentic writes `events.ndjson` for the run via `NormalizedEventSink`
- Codex milestone lines appear as canonical events in `events.ndjson`
- final structured output remains available after the run
- the bridge still works when streaming is disabled (no sinks registered)
- the shared harness is not modified by this packet
- Codex-specific extraction and registration logic lives in `src/audiagentic/execution/providers/adapters/codex.py`

## Entry criteria

Before starting, confirm all of the following are true:

- `PKT-PRV-048` is at least `READY_FOR_REVIEW`
- `PKT-PRV-032` remains `READY_FOR_REVIEW` or better
- Codex runs already succeed without extractor changes
- shared stream artifacts already exist for at least one Codex job under `.audiagentic/runtime/jobs/<job-id>/`

## Config and runtime contract

- read `stream-controls` from the normalized launch request / packet context
- project defaults currently come from `.audiagentic/project.yaml` under `prompt-launch.default-stream-controls`
- do not add Codex-only stream config keys in this packet
- do not change runtime artifact locations; continue using:
  - `.audiagentic/runtime/jobs/<job-id>/stdout.log`
  - `.audiagentic/runtime/jobs/<job-id>/stderr.log`
  - `.audiagentic/runtime/jobs/<job-id>/events.ndjson`

## Implementation checklist

1. read the shared sink contract in `src/audiagentic/streaming/provider_streaming.py` and `src/audiagentic/streaming/sinks.py`
2. add or finish `CodexEventExtractor` in `src/audiagentic/execution/providers/adapters/codex.py`
3. map Codex milestone lines into canonical event kinds before forwarding to `NormalizedEventSink`
4. keep Codex sink registration in the Codex-owned adapter/bridge seam only
5. verify the non-streaming path still works when `stream-controls.enabled` is false
6. add provider integration tests for event extraction and artifact creation

## Exit criteria

This packet is ready for review when all of the following are true:

- Codex writes canonical records into `events.ndjson`
- Codex extractor logic lives only in `src/audiagentic/execution/providers/adapters/codex.py`
- shared harness files are unchanged except for test/support changes explicitly required by this packet
- streaming-disabled runs still succeed
- docs and packet notes still describe Codex as a provider-owned extractor on top of the shared harness

## Validation commands

Run at minimum:

```powershell
python -m pytest tests/integration/providers/test_codex.py -q
python -m pytest tests/unit/providers/test_streaming.py -q
```
