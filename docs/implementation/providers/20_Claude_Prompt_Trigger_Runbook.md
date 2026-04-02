# Claude prompt-trigger implementation runbook

## Purpose

This runbook turns the shared Phase 4.6 prompt-trigger contract into a Claude-specific
implementation plan with two phases:
- **Option A — Baseline (required):** wrapper-driven path with skill definitions and preflight validation
- **Option B — Native Hook (follow-on):** Claude Code `UserPromptSubmit` and `PreToolUse` integration

It covers the Claude chat exposure paths, required repo-local assets, hook configuration,
and smoke tests that prove a tagged prompt can launch the shared workflow runner.

## Scope

This runbook applies to:
- Claude Code CLI (both phases)
- Claude Code VS Code surface (both phases)
- the repository-owned Claude instruction surface (both phases)
- `.claude/settings.json` hook configuration (Option B only)

It does not define the canonical grammar. The grammar remains shared in the Phase 3.2 and
Phase 4.3 docs.

## Required outcomes

Both phases must expose the canonical prompt tags through deterministic paths:
- `@ag-plan`
- `@ag-implement`
- `@ag-review`
- `@ag-audit`
- `@ag-check-in-prep`
- optional `@adhoc` only if the feature gate is enabled

The first non-empty line in the prompt must be recognized before Claude begins planning.
The normalized result must enter the shared launch path without changing the canonical grammar.

**Option A (baseline):** Tags route through the wrapper bridge with preflight validation of
required assets (skills directory, CLAUDE.md, rules).

**Option B (native hook):** Tags route through native Claude Code hooks (UserPromptSubmit,
PreToolUse) without requiring manual wrapper invocation; falls back to wrapper if hooks
unavailable.

## Current repo state

The repo now contains the Claude bridge surface required by this runbook:

- `CLAUDE.md`
- `.claude/rules/prompt-tags.md`
- `.claude/rules/review-policy.md`
- `tools/claude_prompt_trigger_bridge.py`

## Option A — Baseline (wrapper-driven path) — PKT-PRV-033

Claude is supported through a wrapper-driven path with skill definitions and preflight validation.

### Exposure flow (Option A)

1. user types a tagged prompt in Claude Code CLI or the Claude VS Code surface
2. user manually invokes the shared bridge or a skill/tool calls the wrapper bridge
3. `tools/claude_prompt_trigger_bridge.py` reads the raw prompt
4. bridge validates that required assets exist (AGENTS.md, `.claude/rules/`, `.claude/skills/`)
5. bridge resolves the canonical tag and normalizes it into shared launch envelope
6. `CLAUDE.md` and `.claude/rules/*` provide the repository doctrine
7. `.claude/skills/*` define action-specific behavior after normalization
8. shared bridge hands off to `prompt-launch` with preserved provenance

### Required repo-local assets (Option A)

- `CLAUDE.md` (instruction surface)
- `.claude/rules/prompt-tags.md` (tag doctrine)
- `.claude/rules/review-policy.md` (review restrictions)
- `.claude/skills/ag-plan/SKILL.md` (plan action)
- `.claude/skills/ag-implement/SKILL.md` (implement action)
- `.claude/skills/ag-review/SKILL.md` (review action)
- `.claude/skills/ag-audit/SKILL.md` (audit action)
- `.claude/skills/ag-check-in-prep/SKILL.md` (check-in-prep action)
- `tools/claude_prompt_trigger_bridge.py` (wrapper with preflight validation)

### Canonical tag handling (Option A)

The bridge must:
- inspect only the first non-empty line for the canonical tag
- map the tag to the same normalized action as the shared launcher
- preserve provider, surface, and session provenance
- preserve the raw prompt text in metadata
- validate that required skill files exist before launching
- refuse to invent alternate tag meanings

---

## Option B — Native Hook (Claude Code hook integration) — PKT-PRV-055

Claude Code's native `UserPromptSubmit` and `PreToolUse` hooks provide a seamless in-chat
experience where tagging a prompt automatically routes it through the shared bridge.

### Exposure flow (Option B)

1. user types a tagged prompt in Claude Code CLI or the Claude VS Code surface
2. `UserPromptSubmit` hook intercepts the prompt before planning starts
3. hook resolves the canonical tag and injects the normalized launch metadata
4. hook invokes the shared bridge (no manual wrapper call needed)
5. `PreToolUse` hook enforces stage restrictions (e.g., no write tools during review)
6. `.claude/settings.json` configures the hook chain
7. `CLAUDE.md` and `.claude/rules/*` define the repository doctrine
8. shared bridge hands off to `prompt-launch` with preserved provenance

### Required repo-local assets (Option B)

All of Option A assets, plus:

- `.claude/settings.json` (hook configuration for UserPromptSubmit and PreToolUse)
- hook invocation logic (scripts or embedded) that calls the shared bridge
- fallback detection to gracefully degrade to wrapper when hooks unavailable

### Canonical tag handling (Option B)

The hook must:
- inspect only the first non-empty line for the canonical tag
- route to shared bridge instead of manual wrapper invocation
- map the tag to the same normalized action as the shared launcher
- preserve provider, surface, and session provenance
- preserve the raw prompt text in metadata
- detect when hook chain is unavailable and fall back to wrapper
- refuse to invent alternate tag meanings

### Fallback to Option A

If the hook chain is unavailable (hooks not configured, Claude Code version incompatible, etc.):
- Option A wrapper remains fully functional
- users can still invoke `tools/claude_prompt_trigger_bridge.py` manually
- no error or exception blocks the user
- the shared grammar is unchanged

## Implementation sequence for both options

### Phase 1: Option A (baseline) — PKT-PRV-033

1. add or update `CLAUDE.md`
2. add prompt-tag and review-policy rules under `.claude/rules/`
3. add the five canonical skills under `.claude/skills/`
4. add preflight validation to `tools/claude_prompt_trigger_bridge.py` (check for required assets)
5. add tests for missing-assets validation error
6. verify CLI and optional VS Code surfaces can manually invoke the wrapper bridge
7. update build registry to mark PKT-PRV-033 VERIFIED

### Phase 2: Option B (native hook) — PKT-PRV-055

1. create or update `.claude/settings.json` with UserPromptSubmit and PreToolUse hook config
2. implement hook-invocation logic that routes to shared bridge
3. implement PreToolUse stage-restriction enforcement
4. add hook availability detection and fallback handling
5. add smoke tests for hook chain
6. add fallback tests (hook unavailable → wrapper works)
7. verify CLI and VS Code surfaces behave identically through hook chain
8. update build registry to mark PKT-PRV-055 VERIFIED

## Implementation sequence

1. add or update `CLAUDE.md`
2. add prompt-tag and review-policy rules under `.claude/rules/`
3. add or update the five canonical skills
4. wire `UserPromptSubmit` to the shared trigger bridge
5. wire `PreToolUse` to the stage restriction policy
6. verify CLI and VS Code surfaces use the same normalized request shape
7. add smoke tests for `@ag-plan`, `@ag-implement`, and `@ag-review`

## Smoke test matrix

### Option A (baseline) — CLI smoke tests

- `@ag-plan` normalizes and reaches shared launcher via wrapper bridge
- `@ag-implement` normalizes and reaches shared launcher via wrapper bridge
- `@ag-review` normalizes and reaches shared launcher via wrapper bridge
- missing required assets (CLAUDE.md, skills) returns validation error before launch
- provider override works: `@ag-plan provider=cline` launches Cline job

### Option B (native hook) — Hook smoke tests

- `@ag-plan` via hook reaches shared launcher without manual wrapper invocation
- `@ag-implement` via hook normalizes and reaches shared launcher
- `@ag-review` via hook normalizes and reaches shared launcher
- `@ag-plan provider=cline` via hook launches Cline sub-agent
- `PreToolUse` restricts tools per stage (e.g., no write tools during review)
- missing hook chain falls back to Option A wrapper bridge (optional fallback test)
- CLI and VS Code surfaces produce identical normalized requests through hook chain

### VS Code smoke tests (both options)

- the same three tags produce the same normalized launch envelope
- the same repo rules apply
- the same tool restrictions apply

## Acceptance criteria for completion

### Option A completion (PKT-PRV-033)

- tagged Claude prompts invoke the shared launcher path via wrapper bridge
- Claude-specific instructions remain isolated from shared grammar docs
- skill definitions are in place and define action behavior
- preflight validation prevents launch if required assets are missing
- wrapper fallback works if hook chain is partial (Option B uses this fallback)
- CLI and VS Code behavior are aligned

### Option B completion (PKT-PRV-055)

- tagged Claude prompts invoke the shared launcher path via native hook without wrapper invocation
- hook chain preserves provenance and raw prompt metadata
- fallback to Option A wrapper bridge works when hook chain is unavailable
- `PreToolUse` enforces stage restrictions
- CLI and VS Code surfaces behave identically
- hook-invoked and wrapper-invoked paths produce identical normalized requests

## Live stream expectations (Phase 4.9)

Claude is a follow-on candidate for live console and runtime progress capture after the
first-wave providers (Cline, Codex) have validated the harness.

Implementation uses the PKT-PRV-048 generic sink harness.  Claude does not own any
persistence logic; stdout/stderr are captured by AUDiaGentic via sinks.

For the first pass:

- the bridge registers `ConsoleSink`, `RawLogSink`, and `NormalizedEventSink` for each Claude run
- console mirroring is controlled by `ConsoleSink` presence, not a boolean flag
- `events.ndjson` is written to the job runtime folder for every streaming-enabled run
- disabling streaming means not registering the sinks; the bridge path is otherwise unchanged
- a provider-specific event extractor may be added later if Claude emits structured progress
  output; until then, raw stdout lines pass through to `NormalizedEventSink` directly

## Rollback guidance

### Option A rollback

- revert skill definitions and rule files
- remove preflight validation from the wrapper bridge
- leave the shared prompt grammar untouched
- keep the shared bridge contract intact so other providers remain unaffected

### Option B rollback

- revert `.claude/settings.json` hook configuration
- leave Option A wrapper and skills untouched
- remove hook-invocation logic
- the wrapper fallback (Option A) remains fully functional

## Related docs

### Baseline (Option A)

- `docs/implementation/packets/phase-4/PKT-PRV-033.md` — baseline wrapper path with skills
- `docs/implementation/providers/13_Claude_Code_Tag_Execution_Implementation.md`

### Native hook (Option B)

- `docs/specifications/architecture/45_DRAFT_Claude_UserPromptSubmit_Hook_Contract.md` — hook contract
- `docs/implementation/packets/phase-4/PKT-PRV-055.md` — native hook integration packet
- `docs/implementation/providers/33_Claude_Native_Hook_Runbook.md` — detailed hook implementation guide

### Shared

- `docs/specifications/architecture/29_DRAFT_Provider_Prompt_Trigger_Launch_Behavior.md`
- `docs/specifications/architecture/02_Claude.md` (if exists)
- `docs/implementation/packets/phase-4/PKT-PRV-048.md` — shared sink harness
