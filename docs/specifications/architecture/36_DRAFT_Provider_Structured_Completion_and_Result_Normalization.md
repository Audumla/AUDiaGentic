# DRAFT — Provider Structured Completion and Result Normalization

## Purpose

This specification defines how prompt-triggered provider sessions should report their final result back to AUDiaGentic in a structured, machine-readable form.

The goal is to make the end-to-end path consistent across providers while allowing each provider to use the most reliable native surface available:

- some providers should return JSON on stdout
- some should write a final result file that AUDiaGentic reads
- some should use hook-backed or instruction-backed wrapper flows
- some should rely on a shared bridge that normalizes the final payload

AUDiaGentic owns:

- live capture
- structured result normalization
- final artifact persistence
- job/review status recording

Providers own only the execution surface that produces the result.

## Scope

This spec applies to the prompt-trigger execution path for:

- `claude`
- `codex`
- `cline`
- `gemini`
- `copilot`
- `local-openai`
- `qwen`

`continue` remains a future integration and is intentionally out of scope for the first pass of this phase.

## Shared result contract

Providers SHOULD return a final structured payload that can be normalized into the following canonical fields:

- `status`
- `decision`
- `findings`
- `recommendation`
- `follow-up-actions`
- `evidence`
- `notes`
- `stdout`
- `stderr`
- `returncode`

If a provider cannot emit the final structured payload directly, AUDiaGentic may normalize from:

- a JSON block in stdout
- a JSON file emitted by the provider wrapper
- a final-message file emitted by the provider CLI
- a hook summary produced by the provider instruction surface

## Provider selection rule

The implementation should prefer the most stable path available for each provider:

1. native structured output if the provider already emits it reliably
2. provider CLI stdout JSON or final-message file
3. provider instruction surface plus wrapper normalization
4. shared bridge fallback

## Default JSON shape

The canonical shape is:

```json
{
  "contract-version": "v1",
  "provider-id": "cline",
  "job-id": "job_20260331_0005",
  "subject": {
    "kind": "job",
    "job-id": "job_20260331_0001"
  },
  "decision": "approved",
  "recommendation": "pass-with-notes",
  "findings": [],
  "follow-up-actions": [],
  "evidence": [],
  "notes": [],
  "stdout": "",
  "stderr": "",
  "returncode": 0
}
```

## Normalization rules

- Missing `findings` and `follow-up-actions` default to empty arrays.
- Missing `recommendation` defaults to `pass-with-notes`.
- Missing `decision` is derived from the review bundle when possible.
- The normalized payload must preserve the raw provider output for troubleshooting.
- The normalized payload must not hide the fact that a fallback path was used.

## Provider-specific method summary

### Cline

- Best method: JSON stream on stdout with wrapper parsing.
- Reason: the CLI already emits task lifecycle events and a completion result.
- Required support:
  - `.clinerules`
  - wrapper normalization
  - prompt template that asks for a final JSON summary block

### Codex

- Best method: wrapper-first with `AGENTS.md` / skills plus a final-message file.
- Reason: the CLI already supports an output-last-message path and the repo already uses a Codex wrapper.
- Required support:
  - repo-local prompt bridge
  - `AGENTS.md`
  - skills-backed prompt guidance
  - final-message parsing and JSON normalization

### Claude

- Best method: hook-backed instruction surface with wrapper fallback.
- Reason: Claude Code works best when repo instructions and hooks shape the interaction while the shared bridge remains available.
- Required support:
  - `CLAUDE.md`
  - `.claude/rules`
  - hook-backed prompt capture when stable
  - wrapper fallback for portability

### Gemini

- Best method: wrapper-first with command-template normalization.
- Reason: Gemini responds reliably when the prompt is bounded and the timeout is generous, but native hook behavior should stay guarded until proven.
- Required support:
  - `GEMINI.md`
  - command-template prompt wrapper
  - JSON result template
  - longer timeout defaults

### Copilot

- Best method: wrapper-first with repo instruction files.
- Reason: the provider is most stable when the prompt is driven through repo-local instructions and a shared bridge rather than depending on interactive-only behavior.
- Required support:
  - `.github/copilot-instructions.md`
  - prompt files or agent files
  - wrapper normalization

### local-openai

- Best method: bridge-only with direct response normalization.
- Reason: the backend is already an OpenAI-compatible endpoint, so AUDiaGentic should normalize directly from the response body.
- Required support:
  - shared bridge
  - response-body JSON normalization
  - no native hook dependency

### Qwen

- Best method: bridge-first with CLI fallback normalization.
- Reason: Qwen can be driven through the same shared bridge pattern while keeping its own provider config and CLI surface.
- Required support:
  - shared bridge
  - CLI wrapper or compatible endpoint
  - normalized result parsing

### Continue

- Future integration only.
- Not part of the first executable pass for this phase.

## Design goals

- keep the shared contract small and stable
- allow provider-specific surfaces without duplicating the whole workflow
- make the runtime capture and normalization AUDiaGentic-owned
- keep raw provider output available for diagnosis
- preserve provider-specific hooks or wrappers where they are the most reliable choice

## Implementation note

This spec intentionally does not force every provider to use the same mechanism.
It only requires the same canonical result shape after normalization.
