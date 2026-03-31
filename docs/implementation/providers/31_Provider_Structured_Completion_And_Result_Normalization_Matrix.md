# Provider Structured Completion and Result Normalization Matrix

This matrix records the preferred method for each provider to return a structured final result for prompt-triggered work.

The goal is to keep the runtime capture and persistence owned by AUDiaGentic while allowing each provider to use the most stable native surface available.

## Shared rule

All providers must normalize to the same canonical result shape after execution:

- `status`
- `decision`
- `findings`
- `recommendation`
- `follow-up-actions`
- `evidence`
- `stdout`
- `stderr`

## Provider methods

### Cline

- Preferred method: stdout streaming plus wrapper normalization.
- Native surface: `cline --json`.
- Repo assets: `.clinerules`, `tools/cline_prompt_trigger_bridge.py`.
- Notes:
  - best for progress visibility
  - still needs prompt-shape hardening so the final result is deterministic
  - wrapper should parse a final JSON block or summary record

### Codex

- Preferred method: wrapper-first with `AGENTS.md` / skills plus a final-message file.
- Native surface: `codex exec --output-last-message`.
- Repo assets: `AGENTS.md`, `.agents/skills/*`, `tools/codex_prompt_trigger_bridge.py`.
- Notes:
  - strongest reference implementation for prompt-call mechanics
  - final-message parsing is the stable completion path

### Claude

- Preferred method: hook-backed instruction surface with wrapper fallback.
- Native surface: Claude Code repo instructions and hooks.
- Repo assets: `CLAUDE.md`, `.claude/rules/*`, wrapper bridge.
- Notes:
  - use hooks where available
  - keep wrapper fallback to avoid hook churn

### Gemini

- Preferred method: wrapper-first command-template normalization.
- Native surface: Gemini CLI prompt execution.
- Repo assets: `GEMINI.md`, wrapper bridge.
- Notes:
  - must use generous timeout defaults
  - should request JSON-only completion text

### Copilot

- Preferred method: instruction files plus wrapper normalization.
- Native surface: repo-local Copilot instructions / agent files.
- Repo assets: `.github/copilot-instructions.md`, prompt files, wrapper bridge.
- Notes:
  - avoid interactive-only dependence for the first pass

### local-openai

- Preferred method: bridge-only direct normalization.
- Native surface: OpenAI-compatible endpoint.
- Repo assets: shared prompt bridge.
- Notes:
  - parse response body directly
  - no native hook dependency

### Qwen

- Preferred method: bridge-first normalization.
- Native surface: Qwen CLI or endpoint surface.
- Repo assets: shared prompt bridge and provider config.
- Notes:
  - keep as bridge fallback until a native surface is worth adding

### Continue

- Deferred.

## Reuse guidance

To avoid duplication:

- keep the shared bridge and runtime capture in one place
- keep provider-specific differences in the provider docs and wrapper scripts
- share prompt templates wherever the result shape is the same
- only add provider-specific hooks when they materially improve reliability

## Provider implementation ordering

1. Cline
2. Codex
3. Claude
4. Gemini
5. Copilot
6. local-openai
7. Qwen
8. Continue later as a future integration

## Status note

Cline currently proves the streaming path, but its final structured review output still needs prompt-shape hardening before the review bundle can be considered definitive.
