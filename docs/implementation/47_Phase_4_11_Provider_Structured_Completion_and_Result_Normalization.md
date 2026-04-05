# Phase 4.11 — Provider Structured Completion and Result Normalization

## Purpose

Phase 4.11 standardizes the way prompt-triggered provider sessions hand their final result
back to AUDiaGentic.

The phase does **not** force every provider through the same technical mechanism.
Instead, it defines a shared completion contract and then assigns each provider the most
reliable available path.

## What this phase leaves behind

- a shared structured completion/result contract
- a canonical final-result payload shape
- shared normalization rules for direct versus fallback-derived results
- primary-provider completion integrations for Codex, Cline, Claude, and opencode
- a planned Gemini completion packet so the shared result architecture does not need to be reopened later
- a provider matrix for later-provider rollout without duplicating the shared harness

## Shared outcome

Every provider path must be able to produce a normalized structured result that AUDiaGentic
can store and render.

That result should include, where available:

- status
- decision
- findings
- recommendation
- follow-up actions
- evidence
- stderr/stdout
- return code
- result source
- normalization method
- raw result path

## Shared harness responsibilities

AUDiaGentic owns:

- final result capture
- normalization
- runtime artifact storage
- review-bundle persistence
- progress capture and console mirroring
- direct-versus-fallback result marking

Providers own:

- the prompt execution surface
- any native hooks or wrapper mechanics
- the final structured output or the raw material needed to normalize it

If provider-specific completion prompting needs to change, the behavioral source stays generic
and is rendered into provider-specific surfaces by the shared regeneration facade using
provider-owned renderer definitions. Phase 4.11 must not create separate hand-authored
canonical provider-function definitions per provider.

At the current repository state, that generic provider-function source has now been seeded into
`.audiagentic/skills/`, but the migration/regeneration line is not yet fully complete. That means `PKT-PRV-056` can begin immediately,
while provider-specific packets that need completion prompt/surface changes should wait for
`PKT-PRV-070`. Gemini is included in the planned completion family now so the shared
normalization and provider-surface architecture account for it from the first pass even
though its runtime path remains guarded.

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

Implementation goal:

- stop falling back to synthetic review artifacts when valid provider JSON is present
- make the direct provider result visible in the persisted review report/bundle path

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

Implementation goal:

- use the final-message path as the primary structured completion surface
- make direct provider JSON the canonical persisted review/result when available

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

## Detailed implementation steps

1. Freeze the canonical final-result payload shape in the shared contract and schemas.
2. Add a shared normalization helper that marks direct versus fallback-derived results.
3. Implement Codex structured completion integration.
4. Implement Cline structured completion integration.
5. Implement Claude structured completion integration.
6. Implement opencode structured completion integration.
7. Implement Gemini structured completion integration.
8. Ensure review-report and review-bundle persistence can preserve direct provider findings when parsing succeeds.
9. Ensure fallback-derived results remain explicit rather than silently masquerading as direct provider output.
10. Use the provider matrix to plan later-provider rollouts.

## Tests to add

- shared normalizer accepts canonical provider JSON
- shared normalizer marks fallback-derived results explicitly
- Codex integration parses final-message JSON into the canonical result
- Cline integration parses completion JSON into the canonical result
- Claude integration normalizes hook-backed or wrapper-bounded completion into the canonical result
- opencode integration normalizes CLI JSON or explicit fallback into the canonical result
- Gemini integration normalizes bounded wrapper-driven JSON completion into the canonical result
- review persistence uses direct provider results when available
- raw result material remains available for diagnosis after normalization

## Acceptance criteria for this phase

1. The shared contract is documented.
2. Each provider has a documented preferred completion method.
3. Providers that can stream progress still hand final persistence to AUDiaGentic.
4. Providers that return raw text still normalize to the canonical structured result.
5. The docs make it clear that provider-specific hooks/wrappers are allowed where they reduce duplication or improve stability.
6. The persisted runtime artifact can distinguish direct provider results from fallback-derived results.

## Current status

- Shared live stream and live input are already in progress.
- Cline has a working launch/stream path, but its final review output still needs prompt-shape hardening.
- Codex has a working wrapper-first path.
- The remaining providers are documented here so their result-completion behavior can be implemented consistently without duplicating the shared harness.

## First packet set

- `PKT-PRV-056` - shared provider structured-completion contract + normalization harness
- `PKT-PRV-057` - Codex structured-completion integration
- `PKT-PRV-058` - Cline structured-completion integration
- `PKT-PRV-068` - Claude structured-completion integration
- `PKT-PRV-069` - opencode structured-completion integration
- `PKT-PRV-071` - Gemini structured-completion integration
