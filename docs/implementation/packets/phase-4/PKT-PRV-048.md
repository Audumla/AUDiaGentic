# PKT-PRV-048 — shared provider live-stream capture contract + harness

**Phase:** Phase 4.9
**Status:** READY_FOR_REVIEW
**Primary owner group:** Shared provider capture

## Purpose

Replace the current hard-coded dual/triple sink helper in
`src/audiagentic/streaming/provider_streaming.py` with a generic, pluggable sink architecture
that AUDiaGentic owns end-to-end.  The harness must fan out each captured line or event to
one or more named, independently-configured sinks so that console mirroring, raw log
persistence, normalized event writing, and future destinations (Discord, replay bus, session
observer) can all be added or removed without touching the reader loop.

## Current baseline (what exists today)

Before this packet, `provider_streaming.py` already provided:

- live stdout/stderr capture via a background reader thread per stream
- append-to-disk raw log (`_append_text`)
- optional console tee (`tee_console`)
- in-memory sink (`list[str]`) returned as `StreamedCommandResult`

This packet now provides:

- a named, pluggable sink interface
- normalized `events.ndjson` writing through `NormalizedEventSink`
- per-sink error isolation
- shared sink builders that uplift provider adapters to the `stdout_sinks` / `stderr_sinks` API

What it still does **not** provide:

- provider-event extraction callbacks beyond the current shared event writer
- advanced back-pressure policies
- provider-specific extractor sinks for Codex and Cline

## Scope

- define a `StreamSink` protocol/ABC in the shared streaming module
- implement built-in named sinks:
  - `ConsoleSink` — replaces the `tee_console` flag
  - `RawLogSink` — replaces the `_append_text` path
  - `NormalizedEventSink` — writes canonical `events.ndjson` records
- replace `_reader` hard-coded logic with a loop that calls each registered sink
- update `run_streaming_command` to accept `stdout_sinks` / `stderr_sinks` lists
- keep `StreamedCommandResult` and the in-memory sink as the default fallback
- define the normalized stream event contract (schema + canonical fields)
- define the runtime output layout (path conventions for stdout.log, stderr.log, events.ndjson)
- add console mirroring on/off control through `ConsoleSink` presence, not a boolean flag
- add per-sink error isolation so one failing sink cannot abort the reader thread

## Sink interface (minimum required shape)

```python
class StreamSink(Protocol):
    def write(self, line: str) -> None: ...
    def flush(self) -> None: ...
    def close(self) -> None: ...
```

Built-in implementations live in `src/audiagentic/streaming/sinks.py`.  Future sinks (Discord,
replay, session observer) are added there without modifying the harness.

## Dependencies

- PKT-PRV-031 verified
- PKT-PRV-032 verified
- PKT-PRV-033 verified
- PKT-PRV-037 verified
- PKT-PRV-038 verified

## Not in scope

- Discord overlay implementation (uses the sink interface; does not live here)
- provider-native business logic
- job control semantics
- install/bootstrap orchestration
- per-sink back-pressure or flow-control policies beyond basic error isolation

## Files likely to change

- `src/audiagentic/streaming/provider_streaming.py` — replace hard-coded sinks with sink list
- `src/audiagentic/streaming/sinks.py` — new file: `ConsoleSink`, `RawLogSink`, `NormalizedEventSink`
- `src/audiagentic/streaming/__init__.py`
- `docs/schemas/provider-stream-event.schema.json`
- `docs/schemas/provider-stream-manifest.schema.json`
- `src/audiagentic/execution/providers/adapters/codex.py`
- `src/audiagentic/execution/providers/adapters/cline.py`
- `src/audiagentic/execution/providers/adapters/claude.py`
- `src/audiagentic/execution/providers/adapters/opencode.py`
- tests for each sink, the reader loop, and per-sink error isolation

## Implementation sequence

1. Define the `StreamSink` protocol in `sinks.py`.
2. Implement `ConsoleSink`, `RawLogSink`, `NormalizedEventSink`.
3. Refactor `_reader` to call each registered sink; catch and log per-sink errors so one
   failing sink cannot abort the reader thread or other sinks.
4. Update `run_streaming_command` signature to accept `stdout_sinks` / `stderr_sinks` lists.
5. Define the normalized stream event schema and `events.ndjson` path convention.
6. Uplift the first streaming adapters to explicit sink-list registration.
7. Add tests: each sink independently, reader with multiple sinks, one sink failure does not
   abort others.
8. Uplift the remaining primary wrapper-based providers (Claude and opencode) to the shared
   sink-list registration path so the repo no longer maintains split streaming implementations.

## Acceptance criteria

- `run_streaming_command` accepts a list of sinks for stdout and stderr separately
- `ConsoleSink`, `RawLogSink`, and `NormalizedEventSink` are independently testable
- a sink that raises does not kill the reader thread or other sinks
- the shared streaming adapters now call `run_streaming_command` with explicit sink lists
- Codex, Cline, Claude, and opencode all use the shared sink-list streaming harness
- `events.ndjson` is written for every captured run when `NormalizedEventSink` is present
- console mirroring is controlled by sink presence, not a boolean flag
- PKT-PRV-049 and PKT-PRV-050 can integrate by registering provider-specific extraction
  sinks without modifying the shared harness
