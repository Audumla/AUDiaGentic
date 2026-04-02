# Codex tag execution implementation

Provider: Codex CLI + Codex IDE extension  
Compliance level: B — mapped execution via thin adapter  
Execution state: IMPLEMENTED
Phase: 4.4

## Confirmation summary

Codex supports:
- durable project guidance through `AGENTS.md`
- reusable skills through `.agents/skills/**/SKILL.md`
- CLI slash commands
- IDE slash commands
- explicit skill invocation in CLI/IDE

Codex does **not** currently expose a documented prompt-submit hook equivalent in the
official customization material. Therefore exact first-line canonical `@tag` support
should be implemented through a thin adapter, not by claiming native tag interception.

Current implementation:
- `src/audiagentic/execution/providers/adapters/codex.py` now invokes the local `codex exec`
  CLI with a normalized execution envelope
- the adapter writes the last message to a temp file and normalizes the returned result
- a live smoke test of the wrapper succeeds when `codex` is available on PATH

Current repo state:
- `AGENTS.md`
- `.agents/skills/plan/SKILL.md`
- `.agents/skills/implement/SKILL.md`
- `.agents/skills/review/SKILL.md`
- `.agents/skills/audit/SKILL.md`
- `.agents/skills/check-in-prep/SKILL.md`
- `.agents/skills/adhoc/SKILL.md`
- `tools/codex_prompt_trigger_bridge.py`

Known limitation:
- the packet runner currently provides structural packet context, not a full task
  payload, so Codex can still ask for a more specific execution target when the
  envelope is too sparse
- repo-local `AGENTS.md` and skill files are still follow-on assets if we want the
  provider to use an explicit skill-driven Codex workflow rather than the wrapper alone

## Related docs

- `docs/specifications/architecture/28_Provider_Tag_Execution_Compliance_Model.md`
- `docs/implementation/providers/11_Provider_Tag_Execution_Conformance_Matrix.md`

## Native assets to use

### Project guidance
Use:
- `AGENTS.md`
- optional nested `AGENTS.md` / `AGENTS.override.md` where required

Purpose:
- freeze canonical tag semantics
- define required review doctrine
- define provenance requirements
- define packet/workflow naming conventions

### Skills
Create one Codex skill per canonical function:
- `.agents/skills/plan/SKILL.md`
- `.agents/skills/implement/SKILL.md`
- `.agents/skills/review/SKILL.md`
- `.agents/skills/audit/SKILL.md`
- `.agents/skills/check-in-prep/SKILL.md`
- optional `.agents/skills/adhoc/SKILL.md`

Each skill should:
- state exactly when it should trigger
- state exactly when it should not trigger
- accept normalized payload fields
- call back into the canonical request envelope structure
- reference shared scripts rather than duplicating logic

## Required adapter

### Why it is required
Codex official docs confirm skills, project guidance, and slash commands, but do not
document a pre-planning user-prompt interception hook for arbitrary custom first-line tags.

### Adapter responsibilities
The adapter should:
1. inspect the raw submitted prompt
2. detect canonical first-line tags
3. construct the canonical request envelope
4. invoke the appropriate Codex skill explicitly
5. inject provider execution metadata:
   - `provider = codex`
   - `adapter_mode = wrapper-normalize`
   - `surface = cli` or `surface = vscode`

### Adapter shape
Preferred paths:
- CLI wrapper script for terminal use
- VS Code companion command / launcher for editor use

The adapter should transform:

`@plan packet PKT-JOB-008`

into an explicit skill-directed prompt, for example:

`Use $plan skill with the normalized request envelope below ...`

The adapter must preserve the raw original prompt in metadata.

## CLI path

1. user enters raw prompt
2. wrapper detects canonical tag
3. wrapper writes normalized envelope
4. wrapper launches Codex CLI with a deterministic skill-directed prompt
5. Codex loads `AGENTS.md`
6. Codex uses the selected skill
7. review / implementation restrictions come from the normalized payload and shared rules

## VS Code path

1. user enters raw prompt in extension chat
2. command palette action or extension bridge runs the same normalizer
3. bridge submits the transformed prompt to the Codex extension
4. Codex uses the same project `AGENTS.md` and skills as CLI

## Exact files/settings to plan for later implementation

Repo files:
- `AGENTS.md`
- `.agents/skills/plan/SKILL.md`
- `.agents/skills/implement/SKILL.md`
- `.agents/skills/review/SKILL.md`
- `.agents/skills/audit/SKILL.md`
- `.agents/skills/check-in-prep/SKILL.md`

Local / wrapper files:
- wrapper executable or script
- optional extension-side bridge config
- test harness for canonical smoke tests

## Risks / limits

- no first-party documented raw custom tag hook found
- exact `@tag` UX depends on the adapter
- skill descriptions must be tightly scoped to avoid implicit misfires
- slash commands in Codex are built-in control commands, not a substitute for canonical tags

## Recommendation

Implement Codex only in adapter mode for canonical tags.
Do not state or imply that Codex natively parses arbitrary custom first-line tags today.

## Related docs

- `docs/implementation/providers/22_Codex_Prompt_Trigger_Runbook.md`




