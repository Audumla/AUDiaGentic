# DRAFT: Claude UserPromptSubmit Hook Contract

## Purpose

Define the contract for how Claude Code's `UserPromptSubmit` and `PreToolUse` hooks integrate
with AUDiaGentic's shared prompt-trigger bridge to recognize and launch canonical tagged prompts
natively without requiring a wrapper invocation.

## Scope

This contract applies to:
- Claude Code CLI
- Claude Code VS Code extension
- `.claude/settings.json` hook configuration
- Hook invocation chain: `UserPromptSubmit` → bridge → launch

It does not redefine the shared prompt-trigger grammar. The grammar remains shared
(Phase 3.2, Phase 4.3 docs). This contract only specifies how Claude Code surfaces expose it.

## Hook responsibilities

### UserPromptSubmit hook

**Trigger:** User submits a prompt in Claude Code (CLI or VS Code).

**Responsibilities:**
1. Read the raw prompt text and session metadata (surface, session-id).
2. Inspect the first non-empty line for a canonical tag (`@plan`, `@implement`, `@review`,
   `@audit`, `@check-in-prep`).
3. If no canonical tag is found, return an empty object or false to allow normal planning
   to proceed.
4. If a canonical tag is detected:
   - Extract the tag and any inline parameters (provider, model, context, output, template).
   - Preserve the raw prompt text.
   - Normalize the tag into the same action values as the shared launcher.
   - Inject launch context (provider-id, surface, session-id, workspace root).
   - Call the shared bridge with the normalized envelope.
   - Inject the result into Claude's planning context so the bridge output informs subsequent work.

**Forbidden:**
- Do not invent alternate tags or reinterpret canonical tag meanings.
- Do not change the shared grammar.
- Do not handle raw prompt mutations; the bridge owns that.

### PreToolUse hook

**Trigger:** Claude requests a tool before using it.

**Responsibilities:**
1. Detect which stage (action tag) is active in the current context.
2. Load the tool restriction policy from `.claude/rules/review-policy.md` (or stage-specific
   restriction rules).
3. Filter the requested tools to only those allowed for the current stage.
4. Return the filtered set.

**Examples:**
- During `@review`, block write/mutation tools; allow read-focused analysis tools.
- During `@implement`, allow all tools per the task requirements.
- During `@plan`, allow read tools and output writing, but block implementation.

**Forbidden:**
- Do not bypass stage restrictions.
- Do not add or remove restrictions outside of the rule files.
- Do not change shared tool contracts.

## Hook contract envelope

When UserPromptSubmit detects a canonical tag, it must normalize the prompt into a launch envelope.

### Input to UserPromptSubmit

```json
{
  "raw_prompt_text": "string",
  "session_id": "string",
  "surface": "cli|vscode",
  "workspace_root": "path"
}
```

### Hook detection and normalization

```
1. Extract first non-empty line: "line = raw_prompt_text.split('\n')[0]"
2. Match against canonical tags: "@plan", "@implement", "@review", "@audit", "@check-in-prep"
3. If match found:
   - action = tag name (e.g., "plan")
   - parameters = parse inline params from first line (e.g., "provider=codex id=job_001")
   - preserve full raw_prompt_text
   - preserve session_id, surface, workspace_root
4. Build normalized envelope (pseudocode):
   {
     "surface": "cli|vscode",
     "provider_id": parameters.get("provider") or claude (default),
     "launch_tag": action,
     "raw_prompt": raw_prompt_text,
     "session_id": session_id,
     "workspace_root": workspace_root
   }
5. Call shared bridge:
   python tools/claude_prompt_trigger_bridge.py \
     --project-root <workspace_root> \
     --surface <surface> \
     --provider-id <provider_id> \
     --session-id <session_id> \
     <raw_prompt>
6. Parse bridge result JSON and inject into Claude context
```

### Output from UserPromptSubmit

If a canonical tag is detected and processed:

```json
{
  "launch_tag": "plan|implement|review|audit|check-in-prep",
  "provider_id": "claude|codex|cline|...",
  "job_id": "string",
  "job_status": "created|...",
  "target": {
    "kind": "packet|workspace|adhoc|...",
    "id": "string"
  }
}
```

This object is injected into Claude's planning context so that Claude understands a job has
been launched and can reason about what to do next (e.g., monitor a running job, continue
with follow-up prompts).

If no canonical tag is detected:

```json
{}
```

Return an empty object so normal planning proceeds.

## Fallback contract

If the hook chain is unavailable (hooks not configured, Claude Code version incompatible, etc.):

1. The wrapper bridge `tools/claude_prompt_trigger_bridge.py` remains functional.
2. Users can manually invoke the wrapper bridge from the prompt or from a tool/skill.
3. The shared grammar does not change.
4. The normalized request shape produced by the wrapper path must be identical to the
   hook-invoked path.

**No error or exception should bubble up if hooks are unavailable.** The system gracefully
degrades to the wrapper fallback.

## Stage restriction rules

### For `@review` (review-policy rules)

From `.claude/rules/review-policy.md`:

- review prompts should stay read-focused unless the normalized request explicitly allows more
- do not broaden review into implementation work
- keep tracked docs and release artifacts synchronized with the job record

**Tool restrictions for review:**

- ✅ Allow: Glob, Grep, Read (file inspection)
- ✅ Allow: Bash (read-only, inspection)
- ✅ Allow: TodoWrite (if marking items done, not adding new work)
- 🛑 Block: Edit, Write (no file mutations during review unless explicitly allowed)
- 🛑 Block: Bash write operations (no state-changing operations)

### For `@plan`

- ✅ Allow: Glob, Grep, Read (codebase exploration)
- ✅ Allow: Bash (read-only)
- ✅ Allow: Agent (spawning research/exploration agents)
- 🛑 Block: Edit, Write (no code changes during planning)

### For `@implement`

- ✅ Allow: all tools (full implementation freedom)

### For `@audit`, `@check-in-prep`

- ✅ Allow: Glob, Grep, Read, Bash (read-only, inspection)
- 🛑 Block: Edit, Write, destructive operations

## Conformance requirements

1. **Hook-invoked path** (UserPromptSubmit → bridge) and **wrapper-invoked path** (manual
   wrapper call) must produce identical normalized request shapes.
2. **Tag parsing** must be deterministic: same first line, same action tag, same parameter
   extraction across multiple runs.
3. **Fallback detection** must not corrupt state: if the hook chain is unavailable, gracefully
   degrade to wrapper fallback without error messages propagating to the user.
4. **Provenance preservation** (provider-id, surface, session-id, workspace-root) must survive
   the entire hook chain and be present in the final job record.
5. **CLI and VS Code surfaces** must follow the same hook configuration and produce identical
   behavior.

## Future extensions

- Hook templates for other providers (future Phase 4.6 extensions)
- Conditional hook triggering based on project rules
- Hook telemetry and diagnostics for debugging hook chains
