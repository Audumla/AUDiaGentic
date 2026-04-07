# PKT-PRV-050 — Cline live-stream capture integration

**Phase:** Phase 4.9
**Status:** READY_TO_START
**Primary owner group:** Cline

## Purpose

Wire the Cline prompt-trigger path into the Phase 4.9 generic sink harness so its rich
task-progress output is captured, normalized, and mirrored by AUDiaGentic without Cline
owning any persistence logic.

## Scope

- register `RawLogSink` and `NormalizedEventSink` for Cline bridge runs
- add a `ClineEventExtractor` sink that parses Cline native NDJSON task-progress lines into
  canonical stream events before forwarding to `NormalizedEventSink`
- wire `ConsoleSink` for live console mirroring during Cline runs
- make `src/audiagentic/execution/providers/adapters/cline.py` the Cline-owned home of
  provider-specific stream extraction, NDJSON parsing, and any Cline-only sink registration
  helpers needed for this packet
- capture review output for longer review tasks via the same sink path
- keep bridge behavior unchanged when streaming is disabled (no sinks registered)

## Cline-specific extraction

Cline emits native NDJSON task-progress events.  A `ClineEventExtractor` sink should
translate these into canonical `provider-stream-event` records (task-start, task-progress,
completion) before they reach `NormalizedEventSink`.  This extractor is Cline-owned and does
not belong in the shared harness.

## Dependencies

- PKT-PRV-048 implemented (sink interface + built-in sinks available)
- PKT-PRV-037 verified
- Cline CLI available

## Not in scope

- Cline model selection rewrite
- Cline hook ordering changes
- provider install/bootstrap work
- shared harness modifications

## Files likely to change

- `tools/cline_prompt_trigger_bridge.py` — register sinks before launch
- `src/audiagentic/execution/providers/adapters/cline.py` — `ClineEventExtractor` sink
- Cline-focused streaming tests and fixtures
- tests for Cline stream capture, extractor, and review output

## Ownership boundary

This packet owns Cline-specific changes in `src/audiagentic/execution/providers/adapters/cline.py`
and the Cline bridge registration seam. Shared sink primitives, sink protocols, and generic
runtime persistence remain owned by `PKT-PRV-048`.

## Acceptance criteria

- Cline progress is visible during the run via `ConsoleSink`
- AUDiaGentic writes `events.ndjson` for the run via `NormalizedEventSink`
- Cline native NDJSON events appear as canonical events in `events.ndjson`
- final review output still writes correctly
- the bridge remains usable when streaming is disabled (no sinks registered)
- the shared harness is not modified by this packet
- Cline-specific extraction and registration logic lives in `src/audiagentic/execution/providers/adapters/cline.py`

## Entry criteria

Before starting, confirm all of the following are true:

- `PKT-PRV-048` is at least `READY_FOR_REVIEW`
- `PKT-PRV-037` remains `READY_FOR_REVIEW` or better
- Cline runs already succeed on the shared sink baseline without provider-specific extraction
- shared stream artifacts already exist for at least one Cline job under `.audiagentic/runtime/jobs/<job-id>/`

## Config and runtime contract

- read `stream-controls` from the normalized launch request / packet context
- project defaults currently come from `.audiagentic/project.yaml` under `prompt-launch.default-stream-controls`
- do not add Cline-only stream config keys in this packet
- keep runtime artifact locations unchanged:
  - `.audiagentic/runtime/jobs/<job-id>/stdout.log`
  - `.audiagentic/runtime/jobs/<job-id>/stderr.log`
  - `.audiagentic/runtime/jobs/<job-id>/events.ndjson`

## Implementation checklist

1. read the shared sink contract in `src/audiagentic/streaming/provider_streaming.py` and `src/audiagentic/streaming/sinks.py`
2. add or finish `ClineEventExtractor` in `src/audiagentic/execution/providers/adapters/cline.py`
3. parse Cline NDJSON into canonical event kinds before forwarding to `NormalizedEventSink`
4. keep Cline-specific extraction and registration inside `cline.py`
5. verify review-oriented runs still persist final artifacts correctly
6. add provider integration tests for NDJSON extraction and runtime artifact creation

## Exit criteria

This packet is ready for review when all of the following are true:

- Cline writes canonical records into `events.ndjson`
- Cline extractor logic lives only in `src/audiagentic/execution/providers/adapters/cline.py`
- shared harness files are unchanged except for test/support changes explicitly required by this packet
- streaming-disabled runs still succeed
- final review artifacts still persist after a streamed run

## Validation commands

Run at minimum:

```powershell
python -m pytest tests/integration/providers/test_cline.py -q
python -m pytest tests/unit/providers/test_streaming.py -q
```
