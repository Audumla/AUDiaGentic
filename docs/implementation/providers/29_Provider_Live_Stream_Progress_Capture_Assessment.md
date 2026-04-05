# Provider Live Stream Progress Capture Assessment

Status: assessment draft  
Scope: Phase 4.9 provider live stream and progress capture

## Purpose

Assess the realistic rollout order and implementation method for Phase 4.9.

The primary question is not whether providers can run at all; it is whether AUDiaGentic can
reliably capture their progress while preserving the final structured result and keeping
persistence provider-neutral.

Architectural note:
- Gemini remains guarded in rollout priority, but it is part of the provider-function and
  generated-surface set from the first implementation pass so later runtime uplift does not
  require revisiting the shared architecture.

## Method categories

- `native-event-stream`: provider already emits structured progress events worth normalizing directly
- `stdout-extract`: provider emits raw or semi-structured stdout that can be normalized
- `wrapper-milestones`: provider needs AUDiaGentic-owned wrapper milestone events plus raw log capture
- `response-only`: provider mainly returns a final response and contributes little live progress detail

## Provider matrix

| Provider | Method | First-pass fit | Executable now | Why | Main blocker |
|---|---|---|---|---|---|
| Cline | native-event-stream | High | Yes | `cline --json` already emits rich NDJSON event families | normalized `events.ndjson` writer still needs implementation |
| Codex | wrapper-milestones | High | Partial | stable wrapper path already exists | richer runtime milestone normalization still needs implementation |
| Claude | wrapper-milestones | Medium | Partial | wrapper path is workable, native hooks can add later richness | native hook/stream behavior still needs confirmation |
| opencode | wrapper-milestones | Medium-high | Yes | stable CLI wrapper path now runs through the shared sink harness | richer provider-specific milestone extraction is still a follow-on |
| Gemini | stdout-extract | Medium | Partial | wrapper-first path is workable | task-shaped prompt/runtime behavior still needs tuning |
| Copilot | stdout-extract | Medium | Partial | repo instruction path can feed shared capture | noninteractive/runtime behavior still needs validation |
| local-openai | response-only | Medium | Partial | bridge-only path is straightforward | little native progress richness to normalize |
| Qwen | stdout-extract | Medium | Partial | bridge-first path is workable | native stream richness still unproven |
| Continue | future integration | Future | No | out of active rollout | intentionally deferred |

## Recommended first-wave build order

1. shared stream capture contract + shared writer
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

- Preferred path: normalize native `--json` event families
- Raw retention: keep full NDJSON in `stdout.log`
- Canonical event source: direct provider events
- Owned implementation seam: `src/audiagentic/execution/providers/adapters/cline.py` under
  `PKT-PRV-050`

### Codex

- Preferred path: wrapper-owned milestone events plus raw stdout/stderr retention
- Raw retention: keep raw logs for diagnosis
- Canonical event source: AUDiaGentic wrapper milestones until richer native events are worth integrating
- Owned implementation seam: `src/audiagentic/execution/providers/adapters/codex.py` under
  `PKT-PRV-049`

### Claude

- Preferred path: wrapper milestones first, hook-derived stream enrichment later
- Raw retention: preserve wrapper/provider output
- Canonical event source: wrapper milestones in the first pass

### opencode

- Preferred path: wrapper milestones first, with normalized sink fan-out owned by AUDiaGentic
- Raw retention: preserve stdout/stderr plus normalized event records
- Canonical event source: wrapper milestones in the first pass

### Gemini

- Preferred path: bounded wrapper prompt plus stdout extraction
- Raw retention: preserve stdout/stderr
- Canonical event source: extracted stdout milestones where safe

### Copilot

- Preferred path: wrapper capture plus stdout extraction
- Raw retention: preserve stdout/stderr
- Canonical event source: wrapper milestones until a more stable event surface exists

### local-openai

- Preferred path: response-only
- Raw retention: preserve response body and transport diagnostics
- Canonical event source: synthetic launch/complete milestones from the bridge

### Qwen

- Preferred path: bridge-first stdout extraction
- Raw retention: preserve stdout/stderr
- Canonical event source: extracted stdout milestones or wrapper milestones depending on real stream richness
