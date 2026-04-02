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

## Sink architecture (required — not optional)

PKT-PRV-048 must implement a generic pluggable `StreamSink` interface.  The hardcoded
`tee_console` flag and `_append_text` path in `provider_streaming.py` must be replaced.
This is not a style preference — it is the only architecture that allows Discord, replay,
and future sinks to be added without touching the reader loop.

Required built-in sinks in `src/audiagentic/streaming/sinks.py`:

- `ConsoleSink` — replaces `tee_console=True`
- `RawLogSink(path)` — replaces `_append_text(log_path, line)`
- `NormalizedEventSink(path)` — new; writes `events.ndjson`

`run_streaming_command` signature change:

```python
# Before (hardcoded)
run_streaming_command(cmd, stdout_log_path=p, tee_console=True)

# After (sink list)
run_streaming_command(cmd,
    stdout_sinks=[ConsoleSink(), RawLogSink(stdout_log), NormalizedEventSink(events_log)],
    stderr_sinks=[ConsoleSink(sys.stderr), RawLogSink(stderr_log)],
)
```

Provider-specific extraction (Cline NDJSON, Codex milestones) is a sink registered by the
adapter — the shared harness never parses provider output directly.

Per-sink error isolation is required: a sink that raises must not abort the reader thread
or affect other sinks.

## Scope

### Shared work (PKT-PRV-048)

- define the `StreamSink` protocol
- implement `ConsoleSink`, `RawLogSink`, `NormalizedEventSink` in `sinks.py`
- refactor `_reader` in `provider_streaming.py` to call each registered sink
- update `run_streaming_command` to accept `stdout_sinks` / `stderr_sinks` lists
- add per-sink error isolation
- define the live-stream event format and `events.ndjson` path convention
- wire default sinks in `execution.py` so existing paths keep working
- add tests: each sink independently, multiple sinks, one-sink-failure isolation
- keep console teeing resilient so encoding issues cannot crash a successful provider run

### Provider first run (PKT-PRV-049 / PKT-PRV-050)

The first implementation pass should target Cline and Codex.  Each registers its own
extractor sink — the shared harness is not modified:

- **Cline** (`ClineEventExtractor` in `adapters/cline.py`) — parses native NDJSON
- **Codex** (`CodexEventExtractor` in `adapters/codex.py`) — parses wrapper milestone lines

Both extractors forward canonical `provider-stream-event` records to `NormalizedEventSink`.

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
