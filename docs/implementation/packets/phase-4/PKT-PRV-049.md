# PKT-PRV-049 — Codex live-stream capture integration

**Phase:** Phase 4.9
**Status:** DEFERRED_DRAFT
**Primary owner group:** Codex

## Purpose

Wire the Codex prompt-trigger path into the Phase 4.9 generic sink harness so live output is
captured, mirrored, and normalized without Codex owning any persistence logic.

## Scope

- register `RawLogSink` and `NormalizedEventSink` for Codex bridge runs
- add a `CodexEventExtractor` sink that parses Codex wrapper milestone lines into canonical
  stream events before forwarding to `NormalizedEventSink`
- wire `ConsoleSink` for live console mirroring during Codex runs
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
- tests for Codex stream capture and extractor

## Acceptance criteria

- Codex runs with live output visible in the console via `ConsoleSink`
- AUDiaGentic writes `events.ndjson` for the run via `NormalizedEventSink`
- Codex milestone lines appear as canonical events in `events.ndjson`
- final structured output remains available after the run
- the bridge still works when streaming is disabled (no sinks registered)
- the shared harness is not modified by this packet
