# Phase 4.11 — Provider Structured Completion and Result Normalization

## Purpose

Phase 4.11 standardizes the way prompt-triggered provider sessions hand their final result back to AUDiaGentic.

The phase does **not** force every provider through the same technical mechanism.
Instead, it defines a shared completion contract and then assigns each provider the most reliable available path.

## Shared outcome

Every provider path must be able to produce a normalized structured result that AUDiaGentic can store and render.

That result should include, where available:

- status
- decision
- findings
- recommendation
- follow-up actions
- evidence
- stderr/stdout
- return code

## Shared harness responsibilities

AUDiaGentic owns:

- final result capture
- normalization
- runtime artifact storage
- review-bundle persistence
- progress capture and console mirroring

Providers own:

- the prompt execution surface
- any native hooks or wrapper mechanics
- the final structured output or the raw material needed to normalize it

## Recommended provider methods

### Cline

Use:

- `.clinerules`
- `tools/cline_prompt_trigger_bridge.py`
- stdout stream parsing

Best fit:

- Cline is already streaming progress cleanly.
- It should finish by returning a JSON summary block or a parseable completion record.
- AUDiaGentic should normalize the stdout stream into the canonical structured result.

### Codex

Use:

- `AGENTS.md`
- `.agents/skills/*`
- `tools/codex_prompt_trigger_bridge.py`
- `--output-last-message`

Best fit:

- Codex already has a strong wrapper-first path.
- The wrapper should keep the prompt short and request a final JSON result.
- AUDiaGentic should normalize the final-message file into the canonical structured result.

### Claude

Use:

- `CLAUDE.md`
- `.claude/rules/*`
- hook-backed capture when stable
- wrapper fallback

Best fit:

- Claude should prefer the repo instruction path and hook-backed launch when available.
- The wrapper should remain the stable fallback to avoid hook churn.

### Gemini

Use:

- `GEMINI.md`
- wrapper normalization
- a bounded task prompt
- longer timeout defaults

Best fit:

- Gemini should remain wrapper-first.
- The prompt should be compact and explicitly request structured JSON.

### Copilot

Use:

- `.github/copilot-instructions.md`
- prompt files / agent files
- wrapper normalization

Best fit:

- Keep Copilot through repo instructions and a shared wrapper.
- Avoid depending on interactive-only behavior for the core E2E path.

### local-openai

Use:

- shared bridge only
- direct response-body normalization

Best fit:

- The local OpenAI-compatible endpoint should be treated as a direct response target.
- The bridge should normalize the response body without provider-specific hooks.

### Qwen

Use:

- shared bridge
- CLI or endpoint response normalization

Best fit:

- Keep Qwen bridge-first until there is a stable native surface worth integrating.

### Continue

Deferred.

## Acceptance criteria for this phase

1. The shared contract is documented.
2. Each provider has a documented preferred completion method.
3. Providers that can stream progress still hand final persistence to AUDiaGentic.
4. Providers that return raw text still normalize to the canonical structured result.
5. The docs make it clear that provider-specific hooks/wrappers are allowed where they reduce duplication or improve stability.

## Current status

- Shared live stream and live input are already in progress.
- Cline has a working launch/stream path, but its final review output still needs prompt-shape hardening.
- Codex has a working wrapper-first path.
- The remaining providers are documented here so their result-completion behavior can be implemented consistently without duplicating the shared harness.

## Next step

Use this phase as the reference for the provider-specific implementation docs that follow.
