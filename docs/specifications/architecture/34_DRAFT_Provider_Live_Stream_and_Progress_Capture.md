# Provider Live Stream and Progress Capture

## Purpose

Define the live-output contract for provider-backed prompt launches so AUDiaGentic can
capture progress, stream console output, persist artifacts, and later feed the same stream
to overlays such as Discord without moving persistence responsibility into the provider.

This extension is intentionally about **capture and presentation**, not provider business
logic. The provider emits progress; AUDiaGentic owns persistence, rendering, and later
fan-out to other consumers.

## Relationship to existing phases

This is a Phase 4.9 extension that sits after prompt-trigger launch behavior and before the
Discord overlay consumes the same stream family.

Related earlier work:
- Phase 3 launch and review jobs already exist
- Phase 4 provider execution adapters already exist
- Phase 4.6 prompt-trigger launch behavior already exists
- Phase 4.7 provider availability/bootstrap orchestration is drafted
- Phase 4.9 live stream and progress capture is the feature described by this spec

## Design goals

1. Capture live provider progress without requiring the provider to write files.
2. Mirror the same live stream to console and runtime artifacts.
3. Preserve enough structure that a later overlay can subscribe to the same data.
4. Keep provider-specific stream behavior isolated behind the provider adapter or bridge.
5. Make the first implementation pass work for Cline and Codex before broadening to other
   providers.

## Non-goals

- No Discord implementation here.
- No new core job state machine.
- No provider-owned persistence rules.
- No requirement that every provider emits the same shape on day one.

## Core contract

Every streamed launch has three layers:

1. **Raw provider output**
   - stdout
   - stderr
   - any provider-native progress events

2. **AUDiaGentic capture**
   - job-owned append-only event stream
   - raw log files
   - normalized progress records

3. **Final structured artifact**
   - final review report
   - final execution summary
   - final job result payload

AUDiaGentic owns layers 2 and 3. Providers only produce layer 1.

## Stream surfaces

### Console stream

The bridge may tee progress to the console while the task is running.

Useful for:
- local operator feedback
- debugging
- long-running review/implementation tasks

### Job event stream

Each job may emit append-only progress records under the runtime job folder.

Recommended path:

```text
.audiagentic/runtime/jobs/<job-id>/events.ndjson
```

### Raw provider logs

The bridge may also retain raw provider output for debugging or replay.

Recommended paths:

```text
.audiagentic/runtime/jobs/<job-id>/stdout.log
.audiagentic/runtime/jobs/<job-id>/stderr.log
```

## Stream record model

The normalized stream record should include:
- `contract-version`
- `job-id`
- `prompt-id`
- `provider-id`
- `surface`
- `stage`
- `event-kind`
- `message`
- `timestamp`
- optional `details`

Suggested event kinds:
- `task-started`
- `task-progress`
- `tool-started`
- `tool-complete`
- `warning`
- `result`
- `error`
- `complete`

The exact provider-native event format may differ, but AUDiaGentic should normalize it into
these stable kinds for persistence and any later overlay consumption.

## Live stream behavior

1. The bridge launches the provider CLI or provider-native wrapper.
2. The provider emits stdout/stderr and, when available, progress events.
3. AUDiaGentic mirrors the live output to the console if streaming is enabled.
4. AUDiaGentic appends normalized progress records to the job event stream.
5. AUDiaGentic writes the final structured report when the provider finishes.
6. Any later consumer, including Discord, can tail the job event stream instead of parsing
   provider-specific CLI output.

## First-wave providers

### Cline

Cline is a strong first-wave candidate because its CLI already emits rich structured events.
The first pass should capture:
- task start
- task progress
- command execution notices
- retry/error notices
- final completion result

### Codex

Codex is also a first-wave candidate because the repo already has a stable wrapper and
provider execution path. The first pass should capture:
- launch start
- prompt expansion / template selection
- execution summary
- final completion result or failure reason

## Discord handoff

Discord remains an overlay. It should consume the same job event stream and final artifacts
later, without requiring the provider runtime to know anything about Discord.

That means:
- providers do not publish to Discord directly
- AUDiaGentic may publish progress to Discord later by reading the same stream
- the stream contract should remain transport-neutral

## Validation expectations

- live stream capture can be enabled without breaking existing prompt-launch behavior
- console mirroring can be disabled without losing runtime persistence
- final structured artifacts are still written even if live streaming is not used
- Cline and Codex can be tested first without changing the broader provider set
