# Continue tag execution implementation

Provider: Continue CLI + Continue IDE extensions  
Compliance level: B — mapped execution via thin adapter  
Execution state: NOT IMPLEMENTED
Phase: 4.4

## Confirmation summary

Continue provides:
- a shared `config.yaml`
- persistent `rules`
- `prompts`
- prompt markdown files that become slash commands when `invokable: true`
- the same config model for IDE extensions and CLI

This is a strong fit for synchronized behavior, but current documentation does not confirm
a dedicated raw prompt-submit interception hook for arbitrary custom first-line tags.

## Related docs

- `docs/specifications/architecture/28_Provider_Tag_Execution_Compliance_Model.md`
- `docs/implementation/providers/11_Provider_Tag_Execution_Conformance_Matrix.md`

## Native assets to use

### Shared configuration
Use:
- `config.yaml`

Purpose:
- define model roles
- define shared rules
- define prompts
- define MCP/tool surfaces if needed for review/validation support

### Rules
Use rules to freeze:
- canonical tag semantics
- review-mode doctrine
- tracked-doc write restrictions
- provenance requirements

### Invokable prompts
Create prompts for:
- plan
- implement
- review
- audit
- check-in-prep
- optional adhoc

Each prompt should be marked:
- `invokable: true`

This makes the prompt available as a slash command in CLI and IDE modes.

## Required adapter

Because raw custom `@tag` interception is not documented, exact canonical tag UX should
be implemented through a thin adapter.

Responsibilities:
- detect canonical tag
- build canonical envelope
- map to the matching Continue invokable prompt
- preserve raw prompt text and source surface

## CLI path

1. wrapper detects canonical tag
2. wrapper rewrites to the corresponding Continue prompt invocation
3. Continue loads rules and config
4. execution proceeds with the selected prompt

## VS Code path

1. extension-side launcher detects canonical tag
2. launcher invokes the same mapped Continue prompt
3. IDE and CLI remain aligned because both use the same `config.yaml` and prompt files

## Exact files/settings to plan for later implementation

Repo files:
- `config.yaml`
- prompt markdown files for each canonical function
- rules for tag doctrine and execution restrictions

Bridge files:
- shared normalizer
- Continue CLI launcher
- Continue IDE launcher

## Risks / limits

- prompt files are mapped execution, not raw prompt interception
- avoid duplicating tag semantics inside every prompt file
- continue prompt assets should accept normalized payload, not reinterpret it

## Recommendation

Continue should be documented as a synchronized adapter-based provider: excellent for
shared config and shared slash prompts, but not claimed as native first-line `@tag`
interception unless later docs add that capability.

## Related docs

- `docs/implementation/providers/24_Continue_Prompt_Trigger_Runbook.md`




