# Cline tag execution implementation

Provider: Cline editor + Cline CLI  
Compliance level: A — native intercept candidate (guarded rollout)  
Execution state: IMPLEMENTED
Phase: 4.4

## Confirmation summary

Cline documents:
- persistent rules
- workflows that appear as slash commands
- skills
- hooks
- a `UserPromptSubmit` hook
- both editor and CLI surfaces

That is enough to support native canonical tag interception in principle, but the realistic
first pass should still keep the CLI-backed execution wrapper and treat hook-native behavior
as a hardening step that needs local validation.

Current repo state:
- `.clinerules/prompt-tags.md`
- `.clinerules/review-policy.md`
- `tools/cline_prompt_trigger_bridge.py`
- shared bridge harness in `src/audiagentic/jobs/prompt_trigger_bridge.py`

## Related docs

- `docs/specifications/architecture/28_Provider_Tag_Execution_Compliance_Model.md`
- `docs/implementation/providers/11_Provider_Tag_Execution_Conformance_Matrix.md`

## Native assets to use

### Rules
Use:
- `.clinerules/*.md`
- `AGENTS.md` where cross-tool compatibility is useful

Purpose:
- define canonical tag semantics
- define review policy
- define tracked-doc restrictions
- define packet/workflow naming conventions

### Workflows
Create workflow files for discoverability and mapped fallback:
- plan
- implement
- review
- audit
- check-in-prep
- optional adhoc

### Skills
Use skills where richer provider-local procedures are required.

### Hooks
Required:
- `UserPromptSubmit`

Recommended:
- `PreToolUse`
- `TaskStart`
- `TaskComplete`

## Hook implementation strategy

### UserPromptSubmit
Responsibilities:
- inspect raw prompt
- detect canonical tag
- validate allowed tags
- construct canonical launch metadata
- attach context so the next Cline planning cycle is constrained correctly

### PreToolUse
Responsibilities:
- enforce review-mode and stage-specific restrictions
- block or validate dangerous tool calls

## CLI path

1. raw prompt submitted to Cline CLI
2. `UserPromptSubmit` hook runs
3. hook normalizes the prompt into canonical metadata
4. workflows / rules / skills steer execution
5. tool restrictions are enforced by hooks

## Editor path

Use the same repository-owned hooks, workflows, rules, and skills so the editor behaves
like the CLI instead of running a second implementation.

## Exact files/settings to plan for later implementation

Repo files:
- `.clinerules/*.md`
- workflow files
- skill directories
- hook scripts
- optional `AGENTS.md`

Settings:
- enable hooks in Cline config
- ensure workspace trust and repo-level configuration are documented

## Risks / limits

- hook ordering and interaction with workflows must be tested carefully
- do not rely only on slash workflows if the canonical requirement is exact first-line tags
- keep the canonical parser in the hook, not in freeform model behavior

## Recommendation

Cline should be treated as wrapper-implemented first, with a native-intercept path available
for future hardening once hook ordering and workflow interaction are validated.
Use workflows as discoverable aliases, not as the sole tag mechanism, until the native path is
proven stable.

## Related docs

- `docs/implementation/providers/25_Cline_Prompt_Trigger_Runbook.md`




