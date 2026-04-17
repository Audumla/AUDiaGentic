# PKT-PRV-055 — Claude UserPromptSubmit and PreToolUse native hook integration

**Phase:** Phase 4.6  
**Status:** VERIFIED  
**Owner:** Claude (ready to start immediately after PKT-PRV-033)  
**Planned start:** Immediately after PKT-PRV-033 VERIFIED

## Objective

Wire Claude Code's native `UserPromptSubmit` and `PreToolUse` hooks to the shared prompt-trigger
bridge so tagged prompts route through the hook chain instead of requiring a manual wrapper invocation.

## Context

PKT-PRV-033 establishes the baseline wrapper-driven path with skill definitions and preflight
validation. This packet extends that path by adding native Claude Code hook support so users
get a seamless in-chat experience: type the tag, and the hook automatically routes to the
shared bridge without any extra steps.

## Prerequisites

- PKT-PRV-033 VERIFIED (wrapper path with skills + preflight validation complete)
- `.claude/settings.json` hook configuration API is documented
- Claude Code hook examples are available for UserPromptSubmit and PreToolUse

## Scope

This packet owns the following implementation surface:

- `.claude/settings.json` — hook configuration for UserPromptSubmit and PreToolUse
- hook-invocation logic that routes to the shared bridge
- PreToolUse stage-restriction enforcement
- fallback detection and handling when hook chain is partial
- smoke tests for hook availability and routing
- documentation of the Claude-specific hook contract

### It may read from

- shared prompt-launch contracts from PKT-PRV-009, PKT-FND-009
- bridge implementation from PKT-PRV-031
- skill definitions from PKT-PRV-033
- prompt-syntax aliases from `.audiagentic/prompt-syntax.yaml`
- rule guidance from `.claude/rules/`

### It must not edit directly

- shared bridge logic (PKT-PRV-031)
- shared launch contracts
- skill definitions (PKT-PRV-033)
- tracked release docs

## Public contracts used

- shared prompt-launch envelope from Phase 3.2 / Phase 0.2
- provider id selection from Phase 4
- hook availability detection from Claude Code
- fallback bridge contract from PKT-PRV-031
- stage restriction rules from `.claude/rules/review-policy.md`

## Detailed build steps

1. Read `docs/specifications/architecture/45_DRAFT_Claude_UserPromptSubmit_Hook_Contract.md`
   to understand the hook contract and how it differs from the wrapper path.
2. Create or update `.claude/settings.json` with hook configuration for UserPromptSubmit and
   PreToolUse.
3. Implement the hook-invocation logic:
   - read raw prompt text
   - detect first-line canonical tag
   - extract provider override (if supplied)
   - normalize into shared bridge args
   - invoke shared bridge with hook-specific provenance
4. Implement PreToolUse logic to enforce stage restrictions per action tag.
5. Add fallback detection: if hooks are unavailable, log a diagnostic message but do not
   error; the wrapper path remains functional.
6. Add smoke tests for:
   - `@plan` via hook reaches shared launcher
   - `@review` via hook with stage restriction
   - `@plan provider=cline` provider override via hook
   - missing hook chain falls back to wrapper bridge (optional fallback test)
   - CLI and VS Code surfaces behave identically
7. Document the complete hook chain and fallback behavior in comments.

## Pseudocode

```python
# UserPromptSubmit hook logic (pseudocode)
def on_user_prompt_submit(raw_prompt: str, session_metadata: dict) -> dict:
    # read first non-empty line
    first_line = raw_prompt.split('\n')[0] if raw_prompt else ""
    
    # detect canonical tag
    if not _is_canonical_tag(first_line):
        return {}  # no tag, pass through to normal planning
    
    # normalize tag + metadata into bridge args
    bridge_args = _normalize_to_bridge_args(
        raw_prompt,
        first_line,
        session_metadata,
    )
    
    # invoke shared bridge
    result = subprocess.run([
        sys.executable,
        "tools/claude_prompt_trigger_bridge.py",
        "--project-root", ".",
        *bridge_args
    ], capture_output=True, text=True)
    
    # parse result and inject into claude context
    return _inject_launch_context(json.loads(result.stdout))

# PreToolUse hook logic (pseudocode)
def on_pre_tool_use(action_tag: str, tools_requested: list[str]) -> dict:
    # enforce stage restrictions
    allowed_tools = _get_allowed_tools_for_stage(action_tag)
    filtered = [t for t in tools_requested if t in allowed_tools]
    return {"allowed_tools": filtered}
```

## Fixtures to add

- `.claude/settings.json` with UserPromptSubmit and PreToolUse hook configurations
- hook test fixtures proving tag detection and bridge invocation
- fallback test fixture for missing hook chain

## Tests to add

- `@plan` via hook reaches shared launcher (CLI)
- `@review` via hook with provider override (CLI)
- PreToolUse restricts tools per stage
- fallback to wrapper when hook chain unavailable
- CLI and VS Code surfaces produce identical normalized requests
- missing hook chain does not break wrapper fallback

## Acceptance criteria

- tagged Claude prompts can route through native hook without manual wrapper invocation
- hook-invoked path and wrapper-invoked path produce identical normalized request shapes
- PreToolUse restricts tools according to stage restrictions
- fallback bridge works when hook chain is unavailable
- provenance (provider, surface, session) survives normalization through hook chain
- CLI and VS Code surfaces behave identically
- all owned tests pass in isolation
- hook configuration is atomic and idempotent

## Deliverables / artifacts left behind

- `.claude/settings.json` with hook configuration
- hook-invocation and stage-restriction logic
- tests listed above
- documentation updates to explain the hook contract and fallback behavior

## Parallelization note

This packet may not run in parallel. It depends on PKT-PRV-033 being VERIFIED. Once that
dependency is satisfied, this packet can begin.

## Out of scope

- redesigning shared prompt launch contracts
- adding features beyond the hook-invocation path
- changing provider selection or model catalog behavior
- implementing Discord or Phase 5+ features

## Related docs

**Option A (prerequisite):**
- `docs/implementation/packets/phase-4/PKT-PRV-033.md`
- `docs/implementation/providers/34_Claude_Option_A_Completion_Checklist.md` (step-by-step)

**Option B (this packet):**
- `docs/specifications/architecture/45_DRAFT_Claude_UserPromptSubmit_Hook_Contract.md` (hook contract)
- `docs/implementation/providers/35_Claude_Option_B_Implementation_Guide.md` (step-by-step detailed guide with code)
- `docs/implementation/providers/33_Claude_Native_Hook_Runbook.md` (high-level runbook)

**Baseline reference:**
- `docs/implementation/providers/20_Claude_Prompt_Trigger_Runbook.md` (both Option A + Option B overview)
- `docs/implementation/providers/13_Claude_Code_Tag_Execution_Implementation.md` (native hook capabilities)
