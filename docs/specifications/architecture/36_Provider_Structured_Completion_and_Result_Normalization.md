# Provider Structured Completion and Result Normalization

Status: implementation-ready spec

## Purpose

This specification defines how prompt-triggered provider sessions should report their final
result back to AUDiaGentic in a structured, machine-readable form.

The goal is to make the end-to-end path consistent across providers while allowing each
provider to use the most reliable native surface available.

AUDiaGentic owns:

- live capture
- structured result normalization
- final artifact persistence
- job/review status recording

Providers own only the execution surface that produces the result.

Implementation note:
- this phase is part of the shared Phase 4.9 through 4.11 provider-session I/O boundary
- it consumes the runtime capture family established by live stream and live input
- it must not redefine launch grammar, job state rules, or provider selection semantics

## Scope

This spec applies to the prompt-trigger execution path for:

- `claude`
- `codex`
- `cline`
- `gemini`
- `copilot`
- `local-openai`
- `qwen`

`continue` remains a future integration and is intentionally out of scope for the first pass.

## Shared result contract

Providers SHOULD return a final structured payload that can be normalized into the following
canonical fields:

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
- `result-source`
- `normalization-method`
- `raw-result-path`

If a provider cannot emit the final structured payload directly, AUDiaGentic may normalize from:

- a JSON block in stdout
- a JSON file emitted by the provider wrapper
- a final-message file emitted by the provider CLI
- a hook summary produced by the provider instruction surface
- a direct response body from a provider endpoint

Suggested canonical shape:

```json
{
  "contract-version": "v1",
  "provider-id": "cline",
  "job-id": "job_20260402_0001",
  "subject": {
    "kind": "job",
    "job-id": "job_20260402_0001"
  },
  "status": "ok",
  "decision": "approved",
  "findings": [],
  "recommendation": "pass-with-notes",
  "follow-up-actions": [],
  "evidence": [],
  "notes": [],
  "stdout": "",
  "stderr": "",
  "returncode": 0,
  "result-source": "stdout-json",
  "normalization-method": "provider-native-json",
  "raw-result-path": ".audiagentic/runtime/jobs/job_20260402_0001/stdout.log"
}
```

## Provider selection rule

The implementation should prefer the most stable path available for each provider:

1. native structured output if the provider already emits it reliably
2. provider CLI stdout JSON or final-message file
3. provider instruction surface plus wrapper normalization
4. shared bridge fallback

## Normalization rules

- Missing `findings` and `follow-up-actions` default to empty arrays.
- Missing `recommendation` defaults to `pass-with-notes`.
- Missing `decision` is derived from the review bundle when possible.
- The normalized payload must preserve the raw provider output for troubleshooting.
- The normalized payload must not hide the fact that a fallback path was used.
- `result-source` must identify where the final result was obtained, for example `stdout-json`, `stdout-text`, `result-file`, `hook-summary`, or `response-body`.
- `normalization-method` must identify how AUDiaGentic derived the canonical shape.
- if the provider returns only markdown or prose, AUDiaGentic must either:
  - parse a bounded embedded JSON block, or
  - record that structured normalization fell back to a synthetic or derived result
- review reports and review bundles must record when the provider result was direct versus fallback-derived

## Current executable reality

The current runtime already supports:

- provider execution through adapters and wrappers
- raw stdout/stderr preservation
- synthetic review bundle/report fallback when a provider does not return structured JSON

The current runtime does **not yet** fully support:

- deterministic structured completion for every first-wave provider
- consistent provider-specific final-result parsing and provenance tagging
- a canonical explicit marker that distinguishes direct provider JSON from fallback-derived review output

That means Phase 4.11 is the contract-hardening layer that closes the gap between
“provider ran” and “provider returned a canonical final artifact.”

## Provider-specific method summary

### Cline

- Best method: JSON stream on stdout with wrapper parsing.
- Reason: the CLI already emits task lifecycle events and a completion result.
- Required support:
  - `.clinerules`
  - wrapper normalization
  - prompt template that asks for a final JSON summary block
- Current reality:
  - launch and raw stream capture work
  - final review persistence still falls back unless the completion payload is reliably JSON
- First implementation target:
  - make Cline return deterministic JSON for review/plan/implement completion
  - persist the direct provider result instead of a synthetic fallback when parsing succeeds

### Codex

- Best method: wrapper-first with `AGENTS.md` / skills plus a final-message file.
- Reason: the CLI already supports an output-last-message path and the repo already uses a Codex wrapper.
- Required support:
  - repo-local prompt bridge
  - `AGENTS.md`
  - skills-backed prompt guidance
  - final-message parsing and JSON normalization
- Current reality:
  - wrapper-first launch path works
  - final completion normalization still needs the hardened canonical JSON path
- First implementation target:
  - make the final-message path produce deterministic JSON for the shared result envelope

### Claude

- Best method: hook-backed instruction surface with wrapper fallback.
- Reason: Claude Code works best when repo instructions and hooks shape the interaction while the shared bridge remains available.
- Required support:
  - `CLAUDE.md`
  - `.claude/rules`
  - hook-backed prompt capture when stable
  - wrapper fallback for portability
- Recommended completion mode:
  - hook-backed or wrapper-bounded JSON response with shared normalization

### Gemini

- Best method: wrapper-first with command-template normalization.
- Reason: Gemini responds reliably when the prompt is bounded and the timeout is generous, but native hook behavior should stay guarded until proven.
- Required support:
  - `GEMINI.md`
  - command-template prompt wrapper
  - JSON result template
  - longer timeout defaults
- Recommended completion mode:
  - wrapper-first bounded JSON completion with conservative timeout handling

### Copilot

- Best method: wrapper-first with repo instruction files.
- Reason: the provider is most stable when the prompt is driven through repo-local instructions and a shared bridge rather than depending on interactive-only behavior.
- Required support:
  - `.github/copilot-instructions.md`
  - prompt files or agent files
  - wrapper normalization
- Recommended completion mode:
  - wrapper-normalized final result with repo instruction files as the prompt surface

### local-openai

- Best method: bridge-only with direct response normalization.
- Reason: the backend is already an OpenAI-compatible endpoint, so AUDiaGentic should normalize directly from the response body.
- Required support:
  - shared bridge
  - response-body JSON normalization
  - no native hook dependency
- Recommended completion mode:
  - direct response-body normalization with no separate result file path

### Qwen

- Best method: bridge-first with CLI fallback normalization.
- Reason: Qwen can be driven through the same shared bridge pattern while keeping its own provider config and CLI surface.
- Required support:
  - shared bridge
  - CLI wrapper or compatible endpoint
  - normalized result parsing
- Recommended completion mode:
  - bridge-first CLI or endpoint normalization until a stronger native surface is proven

### Continue

- Future integration only.
- Not part of the first executable pass for this phase.

## Design goals

- keep the shared contract small and stable
- allow provider-specific surfaces without duplicating the whole workflow
- make the runtime capture and normalization AUDiaGentic-owned
- keep raw provider output available for diagnosis
- preserve provider-specific hooks or wrappers where they are the most reliable choice

## First packet set

The first executable pass for this phase should be packetized as:

- shared completion/result contract plus shared normalization harness
- Codex structured completion integration
- Cline structured completion integration

Later providers should follow only after the first-wave normalization path is stable.
