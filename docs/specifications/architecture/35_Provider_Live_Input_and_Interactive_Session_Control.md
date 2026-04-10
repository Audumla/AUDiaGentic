# Provider Live Input and Interactive Session Control

Status: implementation-ready spec

## Purpose

Define the interactive-input contract for provider-backed prompt launches so AUDiaGentic can
send follow-up data, pause/resume instructions, or conversational turns into a live job session
without moving session control responsibility into the provider.

This extension is intentionally about **session input and control**, not provider business
logic. The provider receives input; AUDiaGentic owns sequencing, persistence, and later
fan-out to other consumers.

Implementation note:
- this phase is part of the shared Phase 4.9 through 4.11 provider-session I/O boundary
- it reuses the same launch-envelope defaults and runtime persistence seams introduced by live-stream capture
- the packets stay separate, but the implementation should share bridge plumbing with live-stream and structured completion where possible

## Relationship to existing phases

This is a Phase 4.10 extension that sits after live-stream capture and before any later
external surface needs to participate in live conversations.

Related earlier work:
- Phase 3 launch and review jobs already exist
- Phase 4 provider execution adapters already exist
- Phase 4.6 prompt-trigger launch behavior already exists
- Phase 4.9 live stream and progress capture already exists
- Phase 4.10 live input and interactive session control is the feature described by this spec

## Design goals

1. Allow AUDiaGentic to send input into an active provider session.
2. Support mid-run clarification, follow-up prompts, or multi-agent conversation turns when the provider bridge can attach them to a live session.
3. Keep the input path owned by AUDiaGentic so session control and persistence stay consistent.
4. Reuse the same runtime job folder and event stream family established by live capture.
5. Make the first implementation pass work for Cline and Codex before broadening to other providers.

## Non-goals

- No external messaging/control implementation here.
- No new core job state machine.
- No provider-owned persistence rules.
- No requirement that every provider supports true bidirectional session input on day one.

## Current executable reality

The current runtime already supports:

- recording input events against a running job
- persisting controlled input records under the runtime job folder
- exposing a CLI/session-input path owned by AUDiaGentic

The current runtime does **not yet** fully support:

- a long-lived provider-session manager
- guaranteed mid-run input injection into one-shot provider executions
- provider-agnostic pause/resume semantics attached to a live process

That means Phase 4.10 currently has a real persistence harness, but not a complete live-session
attachment layer. The implementation plan must keep those concerns separate.

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

Suggested canonical shape:

```json
{
  "contract-version": "v1",
  "job-id": "job_20260402_0001",
  "prompt-id": "prm_20260402_0001",
  "provider-id": "codex",
  "surface": "cli",
  "stage": "implement",
  "event-kind": "input-submitted",
  "message": "proceed with the provider handoff test",
  "timestamp": "2026-04-02T00:15:00Z",
  "details": {
    "source-kind": "operator-console",
    "sequence": 3
  }
}
```

Normalization rules:
- input records are append-only
- each input record must remain attributable to a job and launch provenance
- raw operator input may be preserved only when it is safe to store durably
- provider-native session metadata may be preserved only when it does not introduce secret/session material
- when a live process cannot consume the input immediately, the record should still be stored as durable intent rather than discarded silently

## Session behavior

1. The bridge launches the provider CLI or provider-native wrapper.
2. The provider emits progress and, when needed, asks for additional input.
3. AUDiaGentic can accept input from the console or another controlled source.
4. AUDiaGentic appends normalized input records to the job input stream.
5. AUDiaGentic forwards the input to the provider session using the selected bridge path when the provider adapter supports an attached live session.
6. The provider continues execution with the new input when live-session attachment is available.
7. Any later consumer can inspect the input stream alongside the live stream and final artifact.

## Session manager seam

True mid-run interaction requires a later session manager seam that can:

- keep the provider process alive across turns
- attach new input to that live process
- correlate provider output with the input turn that caused it
- expose pause/resume/cancel as job-owned control operations

Phase 4.10 should therefore be built in two layers:

1. persistence and capture groundwork
2. live-session attachment and control

The first layer is executable now. The second layer is the follow-on that makes the feature fully interactive.

## First-wave providers

### Cline

Cline is a strong first-wave candidate because its live CLI behavior already makes interactive
turn-taking practical to validate.

The first pass should capture:
- operator follow-up input
- prompt continuation input
- pause/resume style control
- final completion after a mid-run input turn

Recommended implementation method:
- start with recorded operator input plus raw runtime persistence
- attach follow-up input only when the Cline invocation mode can keep a live process open
- do not claim generic mid-run input injection unless the process/session layer proves it

### Codex

Codex is also a first-wave candidate because the repo already has a stable wrapper and provider
execution path.

The first pass should capture:
- follow-up input
- prompt expansion or correction input
- pause/resume style control
- final completion after a mid-run input turn

Recommended implementation method:
- start with AUDiaGentic-owned recorded input and durable job/session artifacts
- use wrapper-driven session correlation first
- attach true mid-run input only when the Codex execution path supports a stable live session

## Provider rollout method

For later providers, choose one of these methods explicitly:

1. recorded-input-only with no live process attachment yet
2. controlled stdin/input forwarding into a live CLI process
3. provider-native conversational session continuation

No provider should blur these levels together in the docs. Each provider must say which level it actually supports.

## External consumer handoff

Any later external messaging or control surface should consume the same job input stream and final artifacts without requiring the provider runtime to know anything about that consumer.

That means:
- providers do not publish directly to an external consumer
- AUDiaGentic may publish session-state changes later by reading the same stream
- the session-control contract should remain transport-neutral
- raw session keys or other secret session material must not be copied into runtime input logs; only redacted handles or secure references may survive beyond the live provider process

## Validation expectations

- session input can be enabled without breaking existing prompt-launch or live-stream behavior
- console mirroring can be disabled without losing runtime persistence
- final structured artifacts are still written even if live input is not used
- Cline and Codex can be tested first without changing the broader provider set
- full mid-run interactive control requires a provider adapter or future session manager that can attach new input to a live process; the persistence harness alone is not sufficient for that guarantee
- a later secure-session feature must provide a non-loggable session-reference path before any sensitive provider session keys are durably stored
- the first implementation pass must distinguish clearly between recorded input, queued input, and actually applied live-session input
