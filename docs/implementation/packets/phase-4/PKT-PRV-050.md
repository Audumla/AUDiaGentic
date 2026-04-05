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
