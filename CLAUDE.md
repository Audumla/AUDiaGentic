<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

# CLAUDE.md

This repository uses AUDiaGentic workflow jobs.

## Prompt tag doctrine

- Parse only the first non-empty line for the workflow tag.
- Keep tag semantics identical to the shared AUDiaGentic launch contract.
- Do not invent provider-specific alternate tags.
- Preserve raw prompt text in provenance metadata.
- Keep provenance visible: provider id, surface, and session id should survive normalization.

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

<!-- AUDIAGENTIC:BEGIN agent-ledger/process -->
## Agent ledger process

For release-affecting work, follow AUDiaGentic agent ledger process.

- Check release ledger state before changing release notes, changelog fragments, or release workflow files.
- Keep release artifacts and job records synchronized with implementation and review outcomes.
- Add or update the release ledger fragment when behavior, public workflow, or generated release output changes.
- Do not bypass ledger updates by editing generated release outputs only.
<!-- AUDIAGENTIC:END agent-ledger/process -->

<!-- AUDIAGENTIC:BEGIN agent-ledger/write-instruction -->
## Ledger write instruction

After completing substantive implementation work, record a change event to the ledger
using the audiagentic-ledger-write MCP tool (record_change_event).
Do not skip this step — the ledger is the authoritative record for release tracking.
<!-- AUDIAGENTIC:END agent-ledger/write-instruction -->

<!-- AUDIAGENTIC:BEGIN source-control/doctrine -->
## Source control doctrine

Use the source control component for all git and GitHub operations.
If the agent-ledger component is installed, record a change event to the
ledger before committing using the audiagentic-ledger-write MCP tool
(record_change_event).
Do not invoke git or GitHub APIs directly — use the MCP tools.
<!-- AUDIAGENTIC:END source-control/doctrine -->
