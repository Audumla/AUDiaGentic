# Provider Live Input Interactive Session Assessment

Status: assessment draft
Scope: Phase 4.10 provider live input and interactive session control

## Purpose

Assess the realistic rollout order for the Phase 4.10 live-input work.

The primary question is not whether providers can run at all; it is whether AUDiaGentic can
reliably inject follow-up input into a live session while preserving the final structured
result.

## First-wave candidates

| Provider | Realistic first-pass fit | Why |
|---|---|---|
| Cline | High | Emits visible progress and already works well as a live CLI session candidate |
| Codex | High | Has a stable wrapper path and a clear prompt-to-job launch flow already in place |

## Follow-on candidates

| Provider | Realistic follow-on fit | Why |
|---|---|---|
| Claude | Medium | Likely workable, but the session-open and follow-up-input behavior should be validated after the first wave |
| Gemini | Medium | Works, but long-running task shape is still more sensitive to prompt framing and timeout policy |
| Copilot | Medium | Can likely be handled through the same bridge model, but the runtime behavior is more CLI-dependent |
| local-openai | Medium | Bridge-only input should work, but the backend may not expose a true conversational session |
| Qwen | Medium | Likely workable through the same bridge model, but session behavior may vary |
| Continue | Future integration | Deferred until the prompt-trigger and install behavior are reintroduced into active rollout |

## Recommendation

Start with:
1. shared live-input capture contract
2. Cline
3. Codex

Then decide whether the other providers should use:
- stdin-style input forwarding only
- normalized session-input events
- or a richer provider-native session input stream
