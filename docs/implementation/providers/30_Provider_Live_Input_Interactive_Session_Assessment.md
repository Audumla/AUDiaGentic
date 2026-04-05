# Provider Live Input Interactive Session Assessment

Status: assessment draft  
Scope: Phase 4.10 provider live input and interactive session control

## Purpose

Assess the realistic rollout order and implementation method for Phase 4.10.

The primary question is not whether providers can run at all; it is whether AUDiaGentic can
reliably capture and eventually attach follow-up input to a live session while preserving the
final structured result.

Architectural note:
- Gemini remains guarded in rollout priority, but it is part of the provider-function and
  generated-surface set from the first implementation pass so later session work consumes the
  same shared provider architecture.

## Session-support categories

- `record-only`: persist input as durable runtime intent, but do not promise live process attachment yet
- `stdin-attach`: input can be forwarded into a live CLI/session when the process model allows it
- `native-session`: provider exposes a stronger conversational/session continuation model
- `future-integration`: not in active rollout

## Provider matrix

| Provider | Method | First-pass fit | Executable now | Why | Main blocker |
|---|---|---|---|---|---|
| Cline | stdin-attach | High | Partial | best current candidate for real interactive CLI turns | needs a real live-session/process manager to prove mid-run attachment |
| Codex | record-only -> stdin-attach | High | Partial | stable wrapper path and strong provenance handling | live-session attachment behavior still needs a dedicated session layer |
| Claude | record-only | Medium | Partial | wrapper/hook path can preserve durable input intent | live-session continuation path not yet proven |
| opencode | record-only | Medium | Partial | wrapper-first CLI path can preserve durable input intent and provenance | live-session attachment behavior still needs a dedicated session layer |
| Gemini | record-only | Medium | Partial | wrapper path is workable | interactive continuation still sensitive to prompt/runtime behavior |
| Copilot | record-only | Medium | Partial | wrapper path can preserve input intent | live-session continuation still unproven |
| local-openai | response-only | Medium | Partial | input can be captured against the job even without a session | no strong live conversational/session seam yet |
| Qwen | record-only | Medium | Partial | bridge-first path can preserve input intent | true interactive continuation still unproven |
| Continue | future integration | Future | No | out of active rollout | intentionally deferred |

## Recommended first-wave build order

1. shared live-input capture contract + shared persistence harness
2. Cline
3. Codex
4. Claude
5. opencode
6. Gemini
7. Copilot
8. local-openai
9. Qwen
10. Continue later

## Provider-specific guidance

### Cline

- First-pass claim: recorded input plus eventual live CLI attachment
- Do not overclaim: mid-run interactive injection is not complete until a session manager proves it

### Codex

- First-pass claim: durable recorded input and wrapper-side correlation
- Do not overclaim: true live-session continuation is still a follow-on

### Claude

- First-pass claim: recorded input and hook/wrapper provenance
- Do not overclaim: hook presence does not automatically imply stable mid-run continuation

### opencode

- First-pass claim: recorded input and wrapper-side provenance
- Do not overclaim: a wrapper-backed CLI path is not yet a live-session manager

### Gemini

- First-pass claim: recorded input only
- Do not overclaim: wrapper continuity is not the same as a live session

### Copilot

- First-pass claim: recorded input only
- Do not overclaim: prompt resubmission is not the same as interactive turn attachment

### local-openai

- First-pass claim: recorded input plus request/response correlation only
- Do not overclaim: endpoint requests do not imply a durable session

### Qwen

- First-pass claim: recorded input only
- Do not overclaim: bridge-first runtime support does not equal a live-session manager
