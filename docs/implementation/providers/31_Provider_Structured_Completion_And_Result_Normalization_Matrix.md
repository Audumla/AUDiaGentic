# Provider Structured Completion and Result Normalization Matrix

This matrix records the preferred method for each provider to return a structured final result
for prompt-triggered work.

The goal is to keep runtime capture and persistence owned by AUDiaGentic while allowing each
provider to use the most stable native surface available.

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
- `returncode`
- `result-source`
- `normalization-method`

## Completion method categories

- `native-json`: provider already returns reliable JSON suitable for direct normalization
- `stdout-json`: provider returns JSON in stdout or NDJSON completion output
- `result-file`: provider writes a final result file or last-message file
- `wrapper-derived`: provider returns prose or mixed output and the wrapper derives the canonical shape
- `response-body`: provider endpoint body is the canonical result source

## Provider matrix

| Provider | Preferred method | Build order | Current reality | Key hardening needed |
|---|---|---|---|---|
| Cline | stdout-json | 1 | launch/stream path works, final review still falls back when JSON is not reliable | prompt-shape hardening and deterministic completion parsing |
| Codex | result-file | 2 | wrapper-first path works | deterministic final-message JSON path |
| Claude | wrapper-derived -> native-json | 3 | wrapper path is viable, hook path is promising | stable JSON completion guidance and hook fallback rules |
| Gemini | wrapper-derived -> stdout-json | 4 | wrapper path exists but task shape is sensitive | bounded prompt and deterministic JSON completion |
| Copilot | wrapper-derived | 5 | wrapper/instruction path exists | stable noninteractive final result shaping |
| local-openai | response-body | 6 | direct endpoint path is straightforward | canonical mapping from response body to result envelope |
| Qwen | stdout-json or response-body | 7 | bridge-first path exists | stable completion surface and parsing rules |
| Continue | future integration | later | out of active rollout | deferred |

## Provider methods

### Cline

- Preferred method: stdout JSON or parseable completion record
- Native surface: `cline --json`
- Repo assets: `.clinerules`, `tools/cline_prompt_trigger_bridge.py`
- Rules:
  - keep raw NDJSON in `stdout.log`
  - persist direct provider findings when parsing succeeds
  - mark fallback-derived review results explicitly when parsing fails

### Codex

- Preferred method: final-message or result file normalization
- Native surface: `codex exec --output-last-message`
- Repo assets: `AGENTS.md`, `.agents/skills/*`, `tools/codex_prompt_trigger_bridge.py`
- Rules:
  - treat final-message output as the primary canonical completion source
  - preserve raw stdout/stderr separately for diagnosis
  - mark wrapper-derived results explicitly when direct JSON is unavailable

### Claude

- Preferred method: hook-backed or wrapper-bounded JSON result
- Native surface: `CLAUDE.md`, `.claude/rules/*`, wrapper bridge
- Rules:
  - hook-native completion may be used when stable
  - wrapper fallback remains mandatory for portability

### Gemini

- Preferred method: bounded wrapper-driven JSON completion
- Native surface: `GEMINI.md`, wrapper bridge
- Rules:
  - keep prompts compact
  - use conservative timeout defaults
  - require explicit JSON-only completion prompts

### Copilot

- Preferred method: wrapper-normalized completion
- Native surface: `.github/copilot-instructions.md`, prompt files, wrapper bridge
- Rules:
  - avoid relying on interactive-only behavior
  - make final completion deterministic through repo-owned prompts

### local-openai

- Preferred method: direct response-body normalization
- Native surface: shared bridge plus compatible endpoint response
- Rules:
  - no provider-specific hook requirement
  - response body is the canonical raw result source

### Qwen

- Preferred method: bridge-first stdout or response-body normalization
- Native surface: shared bridge and provider config
- Rules:
  - keep native-hook assumptions guarded
  - document which concrete completion surface is used when implementation begins

## Reuse guidance

To avoid duplication:

- keep the shared bridge and runtime capture in one place
- keep provider-specific differences in the provider docs and wrapper scripts
- share prompt templates wherever the result shape is the same
- only add provider-specific hooks when they materially improve reliability

## Status note

Cline currently proves the launch and raw stream path, but its final structured review output
still needs prompt-shape hardening before the review bundle can be considered definitive.
