# Claude native UserPromptSubmit and PreToolUse hook integration runbook

## Purpose

This runbook turns the Claude UserPromptSubmit hook contract (Phase 4.6 extension,
`docs/specifications/architecture/45_DRAFT_Claude_UserPromptSubmit_Hook_Contract.md`) into
a concrete implementation plan for the native hook path.

It is intentionally narrow: it covers only the Claude Code hook configuration, the bridge
invocation logic from hooks, and the smoke tests that prove a tagged prompt can launch the
shared workflow runner through the native hook chain.

## Scope

This runbook applies to:
- Claude Code CLI hook configuration
- Claude Code VS Code extension hook configuration
- `.claude/settings.json` hook definitions
- UserPromptSubmit → bridge routing
- PreToolUse → stage restriction enforcement
- fallback to wrapper bridge when hooks unavailable

## Hook exposure model

Claude Code exposes hooks natively. A tagged prompt detected by `UserPromptSubmit` is
normalized by the hook, routed to the shared bridge (not the wrapper), and launched
without manual invocation.

This is the native-hook path:
- raw user prompt (first-line canonical tag)
- `.claude/settings.json` hook config
- `UserPromptSubmit` normalization
- shared bridge invocation
- `PreToolUse` stage restriction
- shared `prompt-launch` handoff

## Current repo state

The repo contains these assets for the native hook path:

- `CLAUDE.md` (doctr)
- `.claude/rules/prompt-tags.md` (tag doctrine)
- `.claude/rules/review-policy.md` (review doctrine)
- `.claude/skills/{plan,implement,review,audit,check-in-prep}/SKILL.md` (from PKT-PRV-033)
- `tools/claude_prompt_trigger_bridge.py` (shared bridge wrapper)

**Missing before this packet:**
- `.claude/settings.json` with UserPromptSubmit and PreToolUse hook config

## Hook integration sequence

### Step 1: Create or update `.claude/settings.json`

Define `UserPromptSubmit` hook:

```json
{
  "hooks": {
    "UserPromptSubmit": {
      "description": "Detect canonical prompt tags and route to shared bridge",
      "invoke": "tools/detect_and_launch_prompt_tag.py"
    },
    "PreToolUse": {
      "description": "Enforce stage restrictions per action tag",
      "invoke": "tools/enforce_stage_restrictions.py"
    }
  },
  "instruction-files": [
    "CLAUDE.md"
  ],
  "rules-directories": [
    ".claude/rules"
  ],
  "skills-directories": [
    ".claude/skills"
  ]
}
```

### Step 2: Implement hook logic

Create (or reference) hook handler scripts that:

**For `UserPromptSubmit`:**
1. Read raw prompt text
2. Extract first non-empty line
3. Detect canonical tag using `audiagentic.jobs.prompt_parser`
4. Normalize tag + parameters into bridge args
5. Call `tools/claude_prompt_trigger_bridge.py --project-root . <prompt>`
6. Parse result JSON
7. Inject job context into Claude (so Claude knows a job was launched)
8. Return empty dict if no tag detected (pass through to normal planning)

**For `PreToolUse`:**
1. Detect current action tag from context
2. Load stage restriction rules from `.claude/rules/review-policy.md`
3. Filter tools list to allowed set for the stage
4. Return filtered list

### Step 3: Add smoke tests

Create tests that verify:

**CLI smoke tests:**
- `@plan` via hook normalizes and reaches shared launcher
- `@implement` via hook routes to shared bridge
- `@review` via hook applies stage restrictions (no write tools)
- `@plan provider=cline` provider override via hook launches Cline job
- missing `UserPromptSubmit` hook falls back to wrapper bridge

**VS Code smoke tests:**
- same three tags produce same normalized launch envelope
- PreToolUse restrictions apply in VS Code surface
- fallback bridge works if hook chain is partial

**Hook chain validation tests:**
- hook returns empty dict if first line is not a canonical tag
- hook preserves raw prompt text through normalization
- hook injects correct provenance (provider, surface, session)
- hook handles missing `.claude/settings.json` gracefully

## Acceptance criteria

- `@plan` from Claude Code routes through native hook without manual wrapper invocation
- `@implement`, `@review`, `@audit`, `@check-in-prep` all work through native hook
- provider override in tag (e.g., `@plan provider=cline`) launches sub-agent through specified provider
- `PreToolUse` restricts tools according to stage (e.g., no write tools during `@review`)
- fallback bridge works when hook chain is unavailable
- provenance metadata (provider, surface, session-id) survives hook normalization
- hook-invoked path and wrapper-invoked path produce identical normalized requests
- CLI and VS Code surfaces behave identically
- all owned smoke tests pass

## Rollback guidance

- remove `.claude/settings.json` hook configuration first
- leave skill definitions (from PKT-PRV-033) untouched
- leave `.claude/rules/` and `CLAUDE.md` untouched
- keep the shared bridge contract intact so other providers remain unaffected
- the wrapper fallback will remain functional

## Hook vs. wrapper comparison

| Aspect | Wrapper (PKT-PRV-033) | Native Hook (PKT-PRV-055) |
|---|---|---|
| **Trigger** | Manual: `python tools/claude_prompt_trigger_bridge.py` | Automatic: type tag in chat |
| **Configuration** | Bridge validation in Python | `.claude/settings.json` |
| **Invocation** | User types wrapper command | Claude Code hook intercepts |
| **Stage restriction** | Fallback in bridge | `PreToolUse` hook enforces |
| **Fallback** | N/A (wrapper is fallback) | Falls back to wrapper if unavailable |
| **Experience** | Requires explicit action | Seamless in-chat |
| **First-wave readiness** | PKT-PRV-033: complete baseline | PKT-PRV-055: future enhancement |

## Related docs

- `docs/specifications/architecture/45_DRAFT_Claude_UserPromptSubmit_Hook_Contract.md`
- `docs/implementation/packets/phase-4/PKT-PRV-055.md`
- `docs/implementation/packets/phase-4/PKT-PRV-033.md` (wrapper baseline)
- `docs/implementation/providers/20_Claude_Prompt_Trigger_Runbook.md` (both phases)
- `docs/implementation/providers/13_Claude_Code_Tag_Execution_Implementation.md`
