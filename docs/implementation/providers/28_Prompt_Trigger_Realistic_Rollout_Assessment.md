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
| Continue | High for adapter-based launch | No | `config.yaml` + invokable prompts + wrapper | Good for mapped execution, not raw tag interception. |
| Cline | High for hook-backed launch | Likely yes, once hook ordering is validated | `.clinerules` + hooks + workflows + wrapper fallback | Treat as hook-capable, but keep the first implementation pass conservative. |
| local-openai | High only through the repo bridge | No | repo-owned bridge/wrapper | Backend-only by design; all tag logic must live above the backend. |
| Qwen | Medium-high, but guarded | Maybe, with experimental hooks enabled | `.qwen/settings.json` + hooks + wrapper fallback | Feature-flagged rollout is the safe path because the hook surface is experimental. |

## Rollout grouping

### Group 1 — safest first-wave candidates

- Claude
- Cline
- Codex

These give the best balance of deterministic trigger behavior and maintainable local
configuration surfaces.

### Group 2 — wrapper-first but implementable now

- GitHub Copilot
- Continue
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
- Codex, Copilot, Continue, and local-openai should be treated as wrapper/bridge-first.
- Gemini and Qwen should be rolled out conservatively with fallback paths and smoke tests.

The shared launch contract remains the same for all providers. Only the exposure surface,
bridge path, and feature-gating strategy change.
