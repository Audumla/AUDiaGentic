# Prompt-trigger rollout realism assessment

Status: assessment draft  
Scope: Phase 4.6 provider prompt-trigger launch behavior

## Purpose

This document translates the shared Phase 4.6 prompt-trigger contract into a realistic
provider-by-provider rollout view.

The goal is not to restate the shared grammar. The goal is to answer a practical question:

- which providers can support exact tagged prompt launch now
- which providers need a repo-owned wrapper or bridge
- which providers should be treated as guarded or feature-flagged
- which providers are backend-only and therefore must rely on the repo bridge layer

## Assessment basis

The assessment below uses:

- the shared Phase 4.6 draft spec
- the provider conformance matrix
- the provider-specific prompt-trigger runbooks
- the current local CLI/tool availability on this machine

Current local availability observed in the workspace:

- `codex` available
- `claude` available
- `gemini` available
- `qwen` available
- `cline` available
- `continue` not found on PATH
- `gh` available, which matters for Copilot-flavoured workflows

## Realistic ability by provider

| Provider | Realistic ability | Exact raw `@tag` in provider UI | Practical first path | Notes |
|---|---|---:|---|---|
| Codex | High for wrapper-based launch | No | repo-owned wrapper + `AGENTS.md` + skills | Strongest path is adapter-first; do not rely on undocumented native interception. |
| Claude | High for hook-backed launch | Likely yes, once project hooks are wired | `CLAUDE.md` + `.claude/rules` + `UserPromptSubmit` / `PreToolUse` | Best candidate for a native-hook rollout, but still keep a wrapper fallback. |
| Gemini | Medium | Maybe, but treat as unproven until hook behavior is confirmed | wrapper-normalize first, then hook hardening | Prompt shape sensitivity makes this a tuning-heavy path. |
| GitHub Copilot | High for adapter-based launch | No | `.github/copilot-instructions.md` + prompt files + custom agents + wrapper | Exact literal tag support should stay outside Copilot's semantic routing. |
| Continue | Future integration | No | `config.yaml` + invokable prompts + wrapper | Not part of the active rollout; keep deferred until PATH availability and provider guidance are revisited. |
| Cline | High for hook-backed launch | Likely yes, once hook ordering is validated | `.clinerules` + hooks + workflows + wrapper fallback | Treat as hook-capable, but keep the first implementation pass conservative. |
| local-openai | High only through the repo bridge | No | repo-owned bridge/wrapper | Backend-only by design; all tag logic must live above the backend. |
| Qwen | Medium-high, but guarded | Maybe, with experimental hooks enabled | `.qwen/settings.json` + hooks + wrapper fallback | Feature-flagged rollout is the safe path because the hook surface is experimental. |

## Prompt-calling mechanics map

This map answers the implementation question the same way for every provider:

- what file or surface receives the prompt doctrine
- what component sees the raw tag line first
- what shared code can be reused
- what fallback exists if the native surface is partial

| Provider | Primary instruction surface | First component to see the raw tag line | Shared code / scripts to reuse | Fallback rule |
|---|---|---|---|---|
| Codex | `AGENTS.md` + `.agents/skills/**/SKILL.md` | `tools/codex_prompt_trigger_bridge.py` or a Codex editor wrapper | shared `prompt-trigger-bridge`, shared `prompt-launch`, canonical skills | if interception is partial, keep using the wrapper bridge |
| Claude | `CLAUDE.md` + `.claude/rules/**` | `tools/claude_prompt_trigger_bridge.py` and/or project hooks | shared `prompt-trigger-bridge`, shared `prompt-launch` | if hook ordering is partial, fall back to the bridge and keep canonical tags unchanged |
| Gemini | `GEMINI.md` | `tools/gemini_prompt_trigger_bridge.py` and/or a Gemini command template | shared `prompt-trigger-bridge`, shared `prompt-launch` | if native hooks are unstable, keep the bridge authoritative |
| GitHub Copilot | `.github/copilot-instructions.md` + `.github/agents/**` + prompt files | `tools/copilot_prompt_trigger_bridge.py` | shared `prompt-trigger-bridge`, shared `prompt-launch`, repo prompt/agent assets | if the surface cannot route custom tags, use the wrapper path only |
| Continue | future integration | `tools/continue_prompt_trigger_bridge.py` | shared `prompt-trigger-bridge`, shared `prompt-launch`, config-driven prompts | keep deferred until the provider is reintroduced into the active rollout |
| Cline | `.clinerules/**` + workflows | `tools/cline_prompt_trigger_bridge.py` and validated hook ordering | shared `prompt-trigger-bridge`, shared `prompt-launch` | if hook ordering is partial, keep the bridge path as the source of truth |
| local-openai | repo bridge only | `tools/local_openai_prompt_trigger_bridge.py` | shared `prompt-trigger-bridge`, shared `prompt-launch` | there is no backend-native tag handling; always use the bridge |
| Qwen | `.qwen/settings.json` and optional experimental hooks | `tools/qwen_prompt_trigger_bridge.py` | shared `prompt-trigger-bridge`, shared `prompt-launch` | if hooks are experimental, keep bridge fallback enabled and feature-flag native behavior |

### Codex-first mechanics

Codex is the reference implementation for prompt-calling mechanics in this repo:

1. the first non-empty line contains the canonical tag
2. the bridge reads the raw prompt and preserves provenance
3. `AGENTS.md` tells Codex that the tag is a launch request
4. `.agents/skills/*/SKILL.md` maps the canonical action to a narrow task shape
5. the bridge invokes `prompt-launch`
6. job records, review bundles, and provenance are written by the jobs layer, not by the provider surface

The remaining providers reuse the same canonical launch contract but swap the instruction
surface and the surface adapter that sees the raw prompt first.

## Rollout grouping

### Group 1 — safest first-wave candidates

- Claude
- Cline
- Codex

These give the best balance of deterministic trigger behavior and maintainable local
configuration surfaces.

### Group 2 — wrapper-first but implementable now

- GitHub Copilot
- local-openai

These are fully workable in the repo bridge/wrapper model, but they should not be treated as
native raw-tag providers.

### Group 3 — guarded / tune before broad rollout

- Gemini
- Qwen

These are implementable, but their first pass should stay conservative:

- wrapper or bridge fallback must remain available
- prompt shape and hook ordering need explicit smoke coverage
- feature flags should gate the more experimental paths

## Practical conclusion

The realistic answer is that every provider in scope can participate in Phase 4.6, but not
all of them can do it the same way.

- Claude and Cline are the best candidates for native-hook style rollout.
- Codex, Copilot, and local-openai should be treated as wrapper/bridge-first.
- Gemini and Qwen should be rolled out conservatively with fallback paths and smoke tests.
- Continue remains a future integration and is intentionally excluded from the active rollout at this stage.

The shared launch contract remains the same for all providers. Only the exposure surface,
bridge path, and feature-gating strategy change.

## Live stream rollout realism

For Phase 4.9 live stream and progress capture, the first-wave order should stay:
1. shared live-stream capture contract and harness
2. Cline
3. Codex

That keeps the live-output contract grounded in the providers that already expose useful
progress while leaving the broader provider set for later follow-on capture tuning.

## Live input rollout realism

For Phase 4.10 live input and interactive session control, the first-wave order should stay:
1. shared live-input capture contract and harness
2. Cline
3. Codex

That keeps the interactive-session contract grounded in the providers that already expose
useful live turns while leaving the broader provider set for later follow-on control tuning.
