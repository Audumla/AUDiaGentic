# Provider Live Stream Progress Capture Assessment

Status: assessment draft  
Scope: Phase 4.9 provider live stream and progress capture

## Purpose

Assess the realistic rollout order for the Phase 4.9 live-stream capture work.

The primary question is not whether providers can run at all; it is whether AUDiaGentic can
reliably capture their progress while preserving the final structured result.

## First-wave candidates

| Provider | Realistic first-pass fit | Why |
|---|---|---|
| Cline | High | Emits visible progress events and command notices that make streaming capture easy to validate |
| Codex | High | Has a stable wrapper path and a clear prompt-to-job launch flow already in place |

## Follow-on candidates

| Provider | Realistic follow-on fit | Why |
|---|---|---|
| Claude | Medium | Likely workable, but the native execution and stream shape should be validated after the first wave |
| Gemini | Medium | Works, but long-running task shape is still more sensitive to prompt framing and timeout policy |
| Copilot | Medium | Can likely be captured through the same bridge model, but the runtime behavior is more CLI-dependent |
| local-openai | Medium | Bridge-only capture should work, but the backend may not emit rich progress events |
| Qwen | Medium | Likely workable through the same bridge model, but stream richness may vary |
| Continue | Future integration | Deferred until the prompt-trigger and install behavior are reintroduced into active rollout |

## Recommendation

Start with:
1. shared stream capture contract
2. Cline
3. Codex

Then decide whether the other providers should use:
- CLI stdout/stderr capture only
- progress-event normalization
- or a richer provider-native event stream
