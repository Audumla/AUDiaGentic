<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

# AGENTS.md

This repository uses AUDiaGentic workflow jobs.

## Prompt tag doctrine

- Parse only the first non-empty line for the workflow tag.
- Keep tag semantics identical to the shared AUDiaGentic launch contract.
- Do not invent provider-specific alternate tags.
- Preserve raw prompt text in provenance metadata.
- Keep provenance visible: provider id, surface, and session id should survive normalization.

<!-- AUDIAGENTIC:BEGIN ag-audit/doctrine -->
## Audit action doctrine

When the audit action is triggered: check tracked docs, release artifacts,
and state consistency across the project. Note specific drift, missing evidence,
or broken invariants. Do not mutate tracked docs or code without explicit approval.
Report all drift — do not hide findings.
<!-- AUDIAGENTIC:END ag-audit/doctrine -->

<!-- AUDIAGENTIC:BEGIN ag-check-in-prep/doctrine -->
## Check-in prep action doctrine

When the check-in prep action is triggered: summarize outstanding changes and
their verification state. Confirm baseline assets are current. Report any open
blockers, failing checks, or uncommitted work. Do not introduce new changes or
mark the repo as ready if blockers remain.
<!-- AUDIAGENTIC:END ag-check-in-prep/doctrine -->

<!-- AUDIAGENTIC:BEGIN ag-implement/doctrine -->
## Implement action doctrine

When the implement action is triggered: carry out the requested implementation
work within the stated scope. Do not broaden scope beyond the requested change.
Prefer shared helpers, repository-owned scripts, and existing patterns.
Run verification steps (type checks, tests) when available before declaring done.
<!-- AUDIAGENTIC:END ag-implement/doctrine -->

<!-- AUDIAGENTIC:BEGIN ag-plan/doctrine -->
## Plan action doctrine

When the plan action is triggered: map the requested change into a concrete
execution plan with discrete steps. Identify dependencies, blockers, risks,
and review checkpoints. Do not implement — plan only.
<!-- AUDIAGENTIC:END ag-plan/doctrine -->

<!-- AUDIAGENTIC:BEGIN ag-plan/planning-item-policy -->
## Planning item creation policy

Planning items (requests, specs, plans, tasks) can only be created with explicit user approval.

- Do not autonomously create planning items during analysis, review, or exploration work.
- If analysis suggests a new request or spec is needed, report findings and ask for approval.
- Use the plan action to signal planning work that requires user direction.
- Only create planning items in response to explicit user instruction or approved workflow prompts.
<!-- AUDIAGENTIC:END ag-plan/planning-item-policy -->

<!-- AUDIAGENTIC:BEGIN ag-review/doctrine -->
## Review action doctrine

When the review action is triggered: perform read-focused validation and
completeness review. Identify blockers, missing tests, contract mismatches,
and drift from tracked docs. Do not add implementation work unless explicitly
requested. Do not broaden review into feature-scope changes.
<!-- AUDIAGENTIC:END ag-review/doctrine -->

<!-- AUDIAGENTIC:BEGIN ag-review/review-doctrine -->
## Review doctrine

- Review prompts should stay read-focused unless the normalized request explicitly allows more.
- Do not broaden review into implementation work.
- Keep tracked docs and release artifacts synchronized with the job record.
<!-- AUDIAGENTIC:END ag-review/review-doctrine -->

<!-- AUDIAGENTIC:BEGIN agent-jobs/canonical-rule -->
## Canonical workflow tags

Canonical tags:

- `ag-audit` (aliases: `aga`, `a`)
- `ag-check-in-prep` (aliases: `agc`, `c`)
- `ag-implement` (aliases: `agi`, `i`)
- `ag-plan` (aliases: `agp`, `p`)
- `ag-review` (aliases: `agr`, `r`)

Rules:

- Do not reinterpret these tags — route the raw tagged prompt through the repo-owned bridge.
- Keep tag semantics identical to the shared AUDiaGentic launch contract.
- Keep provenance visible: provider id, surface, and session id should survive normalization.
- Tag definitions are managed in `config/prompt-triggers/tags/`;
  run `python -m audiagentic.components.optional.providers.skill_surfaces --project-root .` after adding, removing, or renaming tags.
<!-- AUDIAGENTIC:END agent-jobs/canonical-rule -->

<!-- AUDIAGENTIC:BEGIN agent-jobs/tag-shortcuts -->
## Tag shortcuts and aliases

Tag and provider aliases are centralized in the tag registry and
`config/prompt-triggers/tags/` and work in all surfaces.

Tag aliases:

- `aga` -> `ag-audit`
- `a` -> `ag-audit`
- `audit` -> `ag-audit`
- `agc` -> `ag-check-in-prep`
- `c` -> `ag-check-in-prep`
- `check-in-prep` -> `ag-check-in-prep`
- `agi` -> `ag-implement`
- `i` -> `ag-implement`
- `implement` -> `ag-implement`
- `agp` -> `ag-plan`
- `p` -> `ag-plan`
- `plan` -> `ag-plan`
- `agr` -> `ag-review`
- `r` -> `ag-review`
- `review` -> `ag-review`

Provider aliases:

- `cx` -> `codex`
- `cld` -> `claude`
- `cln` -> `cline`
- `gm` -> `gemini`
- `opc` -> `opencode`
- `cp` -> `copilot`
<!-- AUDIAGENTIC:END agent-jobs/tag-shortcuts -->

<!-- AUDIAGENTIC:BEGIN source-control/doctrine -->
## Source control doctrine

Use the source control component for all git and GitHub operations.
Before committing, record a change event to the ledger using the
audiagentic-ledger-write MCP tool (record_change_event).
Do not invoke git or GitHub APIs directly — use the MCP tools.
<!-- AUDIAGENTIC:END source-control/doctrine -->
