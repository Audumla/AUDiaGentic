# Claude Code tag execution implementation

Provider: Claude Code CLI + Claude Code VS Code extension  
Compliance level: A — native intercept  
Execution state: IMPLEMENTED
Phase: 4.4

## Confirmation summary

Claude Code exposes:
- project memory/rules via `CLAUDE.md` and `.claude/rules/`
- skills via `.claude/skills/**/SKILL.md`
- a documented `UserPromptSubmit` hook that fires before Claude processes the prompt
- `PreToolUse` hooks that can enforce tool restrictions
- both CLI and VS Code surfaces

This makes Claude Code the strongest native-hook candidate for canonical prompt tags, with
wrapper fallback still worth keeping until the hook path is fully hardened.

Current implementation:
- `src/audiagentic/execution/providers/adapters/claude.py` now invokes the local `claude`
  CLI with a normalized execution envelope
- the wrapper passes the prompt through stdin so multiline packet context survives
- a live smoke test of the wrapper succeeds when `claude` is available on PATH

Known limitation:
- the repo still does not contain `CLAUDE.md`, `.claude/rules/`, or `.claude/skills/`
  assets, so the current implementation is wrapper-based rather than fully hook-driven
- that means the next step for true native intercept is to add those project-local
  Claude assets and hook config, then thread the prompt-tag rules through them

## Related docs

- `docs/specifications/architecture/28_Provider_Tag_Execution_Compliance_Model.md`
- `docs/implementation/providers/11_Provider_Tag_Execution_Conformance_Matrix.md`
- `docs/implementation/providers/20_Claude_Prompt_Trigger_Runbook.md`

## Native assets to use

### Project guidance
Use:
- `CLAUDE.md`
- `.claude/rules/*.md`

Purpose:
- define canonical tag semantics
- define review structure
- define tracked-doc restrictions
- define packet/workflow naming expectations

### Skills
Create:
- `.claude/skills/ag-plan/SKILL.md`
- `.claude/skills/ag-implement/SKILL.md`
- `.claude/skills/ag-review/SKILL.md`
- `.claude/skills/ag-audit/SKILL.md`
- `.claude/skills/ag-check-in-prep/SKILL.md`
- no dedicated adhoc skill file; generic-tag launches are handled by the parser/bridge

### Hooks
Required:
- `UserPromptSubmit`
- `PreToolUse`

Optional:
- `TaskCompleted`
- `SubagentStart` / `SubagentStop` if review fan-out is later added

## Hook implementation strategy

### UserPromptSubmit
Responsibilities:
- inspect raw prompt
- detect canonical first-line tag
- reject unsupported tags
- normalize supported tags into canonical request metadata
- inject or prepend deterministic context so the main Claude run enters the right skill/mode

### PreToolUse
Responsibilities:
- enforce stage restrictions
- tighten tool permissions in review mode
- prevent tracked-doc mutations when not explicitly allowed

## CLI path

1. user submits raw prompt
2. `UserPromptSubmit` hook reads the prompt
3. hook detects canonical tag and emits normalized context
4. Claude proceeds with the appropriate skill/rules
5. `PreToolUse` enforces the execution policy

## VS Code path

The VS Code extension uses the same Claude Code foundation, so the same repository
rules, skills, and hooks should apply. The implementation should treat CLI and VS Code as
two surfaces over the same hook-enabled project configuration.

## Exact files/settings to plan for later implementation

Repo files:
- `CLAUDE.md`
- `.claude/rules/prompt-tags.md`
- `.claude/rules/review-policy.md`
- `.claude/skills/ag-plan/SKILL.md`
- `.claude/skills/ag-implement/SKILL.md`
- `.claude/skills/ag-review/SKILL.md`
- `.claude/skills/ag-audit/SKILL.md`
- `.claude/skills/ag-check-in-prep/SKILL.md`

Config:
- merge hook entries into existing Claude settings rather than overwriting
- define `UserPromptSubmit` handler
- define `PreToolUse` handlers for mode restrictions

## Risks / limits

- multiple hooks must be merged carefully with existing settings
- repository and user-level Claude settings may both exist
- review policy must stay deterministic and not rely on vague natural language matching

## Recommendation

Claude should be the first real provider implementation because it supports true prompt
interception plus downstream tool gating in both terminal and VS Code usage.




