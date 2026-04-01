# Provider Live Input and Interactive Session Control

## Purpose

Define the interactive-input contract for provider-backed prompt launches so AUDiaGentic can
send follow-up data, pause/resume instructions, or conversational turns into a live job session
without moving session control responsibility into the provider.

This extension is intentionally about **session input and control**, not provider business
logic. The provider receives input; AUDiaGentic owns sequencing, persistence, and later fan-out
to other consumers.

Implementation note:
- this phase is part of the shared Phase 4.9 through 4.11 provider-session I/O boundary
- it reuses the same launch-envelope defaults and runtime persistence seams introduced by live-stream capture
- the packets stay separate, but the implementation should share bridge plumbing with live-stream and structured completion where possible

## Relationship to existing phases

This is a Phase 4.10 extension that sits after live-stream capture and before Discord or other
overlays need to participate in live conversations.

Related earlier work:
- Phase 3 launch and review jobs already exist
- Phase 4 provider execution adapters already exist
- Phase 4.6 prompt-trigger launch behavior already exists
- Phase 4.9 live stream and progress capture already exists
- Phase 4.10 live input and interactive session control is the feature described by this spec

## Design goals

1. Allow AUDiaGentic to send input into an active provider session.
2. Support mid-run clarification, follow-up prompts, or multi-agent conversation turns.
3. Keep the input path owned by AUDiaGentic so session control and persistence stay consistent.
4. Reuse the same runtime job folder and event stream family established by live capture.
5. Make the first implementation pass work for Cline and Codex before broadening to other providers.

## Non-goals

- No Discord implementation here.
- No new core job state machine.
- No provider-owned persistence rules.
- No requirement that every provider supports true bidirectional session input on day one.

## Core contract

Every interactive launch has three layers:

1. **Operator or agent input**
   - follow-up prompt text
   - structured session message
   - pause/resume/cancel instruction

2. **AUDiaGentic session control**
   - input queue
   - input request tracking
   - normalized input event records
   - runtime persistence

3. **Final structured artifact**
   - review report
   - implementation summary
   - conversation turn result
   - final job payload

AUDiaGentic owns layers 2 and 3. Providers only receive layer 1 through the bridge or wrapper.

## Session control surfaces

### Console input

The bridge may accept new input while a job is running.

Useful for:
- operator clarification
- multi-step review loops
- multi-agent coordination
- follow-up instructions during long-running tasks

### Job input stream

Each job may emit append-only input records under the runtime job folder.

Recommended path:

```text
.audiagentic/runtime/jobs/<job-id>/input.ndjson
```

### Raw input logs

The bridge may also retain raw user/operator input for debugging or replay.

Recommended paths:

```text
.audiagentic/runtime/jobs/<job-id>/stdin.log
.audiagentic/runtime/jobs/<job-id>/input-events.ndjson
```

## Session record model

The normalized session-input record should include:
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
- `input-requested`
- `input-submitted`
- `input-applied`
- `input-rejected`
- `input-timeout`
- `pause-requested`
- `resume-requested`
- `turn-complete`

The exact provider-native session format may differ, but AUDiaGentic should normalize it into
these stable kinds for persistence and any later overlay consumption.

## Session behavior

1. The bridge launches the provider CLI or provider-native wrapper.
2. The provider emits progress and, when needed, asks for additional input.
3. AUDiaGentic can accept input from the console or another controlled source.
4. AUDiaGentic appends normalized input records to the job input stream.
5. AUDiaGentic forwards the input to the provider session using the selected bridge path.
6. The provider continues execution with the new input.
7. Any later consumer can inspect the input stream alongside the live stream and final artifact.

## First-wave providers

### Cline

Cline is a strong first-wave candidate because its live CLI behavior already makes interactive
turn-taking practical to validate.

The first pass should capture:
- operator follow-up input
- prompt continuation input
- pause/resume style control
- final completion after a mid-run input turn

### Codex

Codex is also a first-wave candidate because the repo already has a stable wrapper and provider
execution path.

The first pass should capture:
- follow-up input
- prompt expansion or correction input
- pause/resume style control
- final completion after a mid-run input turn

## Discord handoff

Discord remains an overlay. It should consume the same job input stream and final artifacts
later, without requiring the provider runtime to know anything about Discord.

That means:
- providers do not publish to Discord directly
- AUDiaGentic may publish session-state changes to Discord later by reading the same stream
- the session-control contract should remain transport-neutral

## Validation expectations

- session input can be enabled without breaking existing prompt-launch or live-stream behavior
- console mirroring can be disabled without losing runtime persistence
- final structured artifacts are still written even if live input is not used
- Cline and Codex can be tested first without changing the broader provider set
