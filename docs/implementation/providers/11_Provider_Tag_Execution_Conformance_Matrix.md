# Provider tag execution conformance matrix

Status: additive design document  
Phase relationship:
- depends on the existing Phase 4.3 provider-surface work
- refines the new Phase 4.4 provider execution implementation work

## Purpose

This document defines exactly how each provider can participate in canonical prompt-tag
execution for the AUDiaGentic workflow system.

Canonical tags:
- `@plan`
- `@implement`
- `@review`
- `@audit`
- `@check-in-prep`
- optional `@adhoc`

Canonical rule:
- provider surfaces must **not** redefine tag semantics
- provider surfaces must either:
  - intercept the tag natively and normalize it into the canonical request envelope, or
  - route the tag through a thin adapter that performs normalization before provider execution

## Compliance levels

### Level A — Native intercept

The provider surface can inspect the raw user prompt before planning/tool execution and
can deterministically convert the first-line tag into the canonical launch envelope.

Use this level when the provider has:
- a prompt-submit hook, before-agent hook, or equivalent pre-planning interception point
- a supported project instruction surface
- a stable way to keep CLI and VS Code aligned

### Level B — Mapped execution

The provider does not expose reliable raw prompt interception for arbitrary custom tags,
but it **does** support reusable commands, prompt files, skills, agents, or workflows.
A thin adapter is required for exact `@tag` compatibility.

### Level C — Backend only

The provider is only a model endpoint or transport. It does not own the user-facing prompt
surface, so canonical tag recognition must happen in the client or wrapper above it.

## Compliance matrix

| Provider | Level | Native raw `@tag` interception | Shared files/settings | Wrapper mandatory for exact literal `@tag` UX |
|---|---|---:|---|---:|
| Codex | B | No confirmed native pre-submit interception | `AGENTS.md`, skills, CLI/IDE commands | Yes |
| Claude Code | A | Yes | `.claude/rules`, `.claude/skills`, hook config | No |
| Gemini CLI / Gemini Code Assist | A | Yes | `GEMINI.md`, commands, hooks, settings | No |
| GitHub Copilot | B | No confirmed native pre-submit interception | `.github/copilot-instructions.md`, prompt files, custom agents, skills | Yes |
| Continue | B | No confirmed native pre-submit interception | `config.yaml`, rules, invokable prompts | Yes |
| Cline | A | Yes | `.clinerules`, workflows, hooks, skills | No |
| Local OpenAI-compatible backend | C | No | base URL and model config only | N/A |
| Qwen Code | A* | Yes, wrapper implemented; hooks are experimental | `.qwen/settings.json`, hooks | No, but feature flag required |

`A*` means "supported with an experimental provider feature that must be guarded and
validated before broad rollout".

## Shared implementation doctrine

### 1. Canonical grammar is upstream of provider behavior

The provider-specific implementation must not reinterpret the meaning of tags.
Every provider must produce the same normalized structure.

Required normalized fields:
- `tag`
- `target.kind`
- `target.ref`
- `workflow_profile`
- `requested_stage`
- `review_mode`
- `source.surface`
- `source.provider`
- `source.session_id` (when available)
- `raw_prompt`
- `normalized_payload`

### 2. Thin adapter rule

If a provider cannot deterministically intercept raw tags before planning, a thin adapter
must be used. The adapter may live in:
- the CLI launcher
- the VS Code extension bridge
- a small wrapper script
- a repo-local helper invoked by the provider surface

The adapter:
- reads the raw prompt
- detects a canonical first-line tag
- validates it
- normalizes it into the canonical request envelope
- invokes the provider-native skill/agent/prompt/workflow surface

The adapter must **not** implement alternate workflow semantics.

### 3. Surface alignment rule

For every provider that has both terminal and editor surfaces:
- the same tag set must be available in both
- the same normalized envelope must be emitted
- the same guardrails must apply
- the same review-mode restrictions must apply

### 4. Required implementation artifacts per provider

Each provider implementation should end with:
- a provider instruction file strategy
- a tag mapping table
- settings ownership
- CLI execution path
- VS Code execution path
- tool restriction strategy
- smoke tests
- known limitations
- synchronization procedure

## Release recommendation

The safest release shape is:
1. freeze contracts and provider implementation docs
2. implement Level A providers first
3. implement Level B providers with adapters second
4. leave Level C providers documented as backend-only

Do not mark provider parity complete until all enabled providers pass the same canonical
smoke tests.

## Realistic rollout guidance

This matrix describes provider capability, not equal implementation effort.

### Highest-confidence first-wave paths

- Claude
- Cline

These are the best candidates for hook-backed, provider-local trigger rollout.

### Wrapper-first but implementable now

- Codex
- GitHub Copilot
- Continue
- local-openai

These should be treated as bridge/wrapper-first surfaces even when local commands or IDE
surfaces are available.

### Guarded rollout

- Gemini
- Qwen

These can be implemented, but the first pass should remain conservative and keep the fallback
bridge path active until the trigger behavior is well proven.

