# Provider Live Stream and Progress Capture

Status: implementation-ready spec

## Purpose

Define the live-output contract for provider-backed prompt launches so AUDiaGentic can
capture progress, mirror console output, persist runtime artifacts, and later feed the same
stream to overlays such as Discord without moving persistence responsibility into the provider.

This extension is intentionally about **capture and presentation**, not provider business
logic. The provider emits progress; AUDiaGentic owns persistence, rendering, and later
fan-out to other consumers.

Implementation note:
- this phase is part of the shared Phase 4.9 through 4.11 provider-session I/O boundary
- it shares launch-envelope defaults and runtime persistence seams with live input and structured completion
- the packets stay separate, but the implementation should reuse the same bridge and artifact layout where possible

## Relationship to existing phases

This is a Phase 4.9 extension that sits after prompt-trigger launch behavior and before the
Discord overlay consumes the same stream family.

Related earlier work:
- Phase 3 launch and review jobs already exist
- Phase 4 provider execution adapters already exist
- Phase 4.6 prompt-trigger launch behavior already exists
- Phase 4.7 provider availability/bootstrap orchestration is drafted
- Phase 4.7 provider availability/bootstrap orchestration remains a separate follow-on and does not block the shared Phase 4.9 contract definition
- Phase 4.9 live stream and progress capture is the feature described by this spec

## Design goals

1. Capture live provider progress without requiring the provider to write files.
2. Mirror the same live stream to console and runtime artifacts.
3. Preserve enough structure that a later overlay can subscribe to the same data.
4. Keep provider-specific stream behavior isolated behind the provider adapter or bridge.
5. Make the first implementation pass work for Cline and Codex before broadening to other providers.

## Non-goals

- No Discord implementation here.
- No new core job state machine.
- No provider-owned persistence rules.
- No requirement that every provider emits the same shape on day one.

## Current executable reality

The current runtime already supports:

- raw `stdout`/`stderr` capture
- optional console teeing
- provider-specific raw stream preservation under the job runtime folder

The current runtime does **not yet** fully support:

- canonical `events.ndjson` writing for every provider event
- a uniform provider-progress normalization layer across all providers
- replay-aware or transport-aware stream publication

This distinction matters for implementation planning:

- Phase 4.9 is buildable now because the raw capture harness exists
- the first implementation pass should harden and normalize the captured stream
- the spec must not overstate raw log capture as equivalent to normalized progress events

## Core contract

Every streamed launch has three layers:

1. **Raw provider output**
   - stdout
   - stderr
   - any provider-native progress events

2. **AUDiaGentic capture**
   - job-owned append-only event stream
   - raw log files
   - normalized progress records once the writer exists

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

Suggested canonical shape:

```json
{
  "contract-version": "v1",
  "job-id": "job_20260402_0001",
  "prompt-id": "prm_20260402_0001",
  "provider-id": "cline",
  "surface": "cli",
  "stage": "review",
  "event-kind": "task-progress",
  "message": "reviewing provider docs",
  "timestamp": "2026-04-02T00:10:00Z",
  "details": {
    "provider-event-type": "task_progress",
    "sequence": 12
  }
}
```

Normalization rules:
- `message` must be safe for durable storage
- `details` may keep provider-native fields only when they do not introduce secret/session material
- provider-native event names should be preserved under a nested field such as `details.provider-event-type`
- normalized records should be append-only
- if normalization fails for a specific raw line, AUDiaGentic should preserve the raw line in the raw log and may emit a best-effort `warning` event instead of aborting the job

## Live stream behavior

1. The bridge launches the provider CLI or provider-native wrapper.
2. The provider emits stdout/stderr and, when available, progress events.
3. AUDiaGentic mirrors the live output to the console if streaming is enabled.
4. AUDiaGentic appends normalized progress records to the job event stream when the writer is enabled.
5. AUDiaGentic writes the final structured report when the provider finishes.
6. Any later consumer, including Discord, can tail the job event stream or raw logs instead of parsing provider-specific CLI output.

## Implementation sequence

The implementation should be staged in this order:

1. preserve raw provider `stdout`/`stderr` deterministically
2. tee live output to console behind explicit stream controls
3. add provider-specific event extraction for first-wave providers
4. normalize first-wave provider events into `events.ndjson`
5. keep the final review/job artifact path working after streaming is enabled
6. only then broaden the normalization layer to other providers

## First-wave providers

### Cline

Cline is a strong first-wave candidate because its CLI already emits rich structured events.

The first pass should capture:
- task start
- task progress
- command execution notices
- retry/error notices
- final completion result

Recommended implementation method:
- parse the `--json` NDJSON output already emitted by the Cline CLI
- preserve the full NDJSON stream in `stdout.log`
- map known event families into canonical `events.ndjson`
- keep unrecognized lines in raw logs without failing the job

### Codex

Codex is also a first-wave candidate because the repo already has a stable wrapper and provider
execution path.

The first pass should capture:
- launch start
- prompt expansion / template selection
- execution summary
- final completion result or failure reason

Recommended implementation method:
- preserve raw Codex stdout/stderr in runtime logs
- emit AUDiaGentic-owned wrapper milestone events when Codex does not emit rich native event families
- normalize final completion/failure into the same runtime event family used by Cline

## Provider rollout method

For later providers, choose one of these methods explicitly:

1. native structured event stream
2. stdout/stderr capture plus provider-specific event extraction
3. wrapper-generated milestone events plus raw log retention

No provider should invent a fourth persistence path outside the shared runtime artifact family.

## Discord handoff

Discord remains an overlay. It should consume the same job event stream and final artifacts
later, without requiring the provider runtime to know anything about Discord.

That means:
- providers do not publish to Discord directly
- AUDiaGentic may publish progress to Discord later by reading the same stream
- the stream contract should remain transport-neutral
- raw session keys or other secret session material must not be copied into runtime stream logs; only redacted handles or secure references may survive beyond the live provider process

## Validation expectations

- live stream capture can be enabled without breaking existing prompt-launch behavior
- console mirroring can be disabled without losing runtime persistence
- final structured artifacts are still written even if live streaming is not used
- Cline and Codex can be tested first without changing the broader provider set
- the first implementation pass may keep raw provider output, but any future secure-session feature must ensure secret session material is omitted or redacted before durable logging
- the first implementation pass must explicitly test Windows console encoding behavior so console teeing cannot crash a successful provider run
