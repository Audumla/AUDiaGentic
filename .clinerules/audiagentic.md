<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

<!-- AUDIAGENTIC:BEGIN agent-jobs/overview -->
# AUDiaGentic agent instructions

This repository uses AUDiaGentic workflow jobs. The instruction blocks below are generated from component sources — do not edit them directly; edit the owning component config and re-run surface apply.
<!-- AUDIAGENTIC:END agent-jobs/overview -->

<!-- AUDIAGENTIC:BEGIN ag-implement/doctrine -->
# Implement action doctrine

When the implement action is triggered: carry out the requested implementation
work within the stated scope. Do not broaden scope beyond the requested change.
Prefer shared helpers, repository-owned scripts, and existing patterns.
Run verification steps (type checks, tests) when available before declaring done.
<!-- AUDIAGENTIC:END ag-implement/doctrine -->

<!-- AUDIAGENTIC:BEGIN ag-plan/doctrine -->
# Plan action doctrine

When the plan action is triggered: map the requested change into a concrete
execution plan with discrete steps. Identify dependencies, blockers, risks,
and review checkpoints. Do not implement — plan only.
<!-- AUDIAGENTIC:END ag-plan/doctrine -->

<!-- AUDIAGENTIC:BEGIN ag-plan/scope-policy -->
# Scope and approval policy

Produce a plan only — do not create or modify tracked work artifacts, or commit to
changes, without explicit user approval.

- Do not autonomously create or modify persistent artifacts during analysis, review, or exploration work.
- If analysis suggests new work is needed, report findings and ask for approval before proceeding.
- Use the plan action to surface work that requires user direction.
- Act only in response to explicit user instruction or approved workflow prompts.
<!-- AUDIAGENTIC:END ag-plan/scope-policy -->

<!-- AUDIAGENTIC:BEGIN ag-review/doctrine -->
# Review action doctrine

When the review action is triggered: perform read-focused validation and
completeness review. Identify blockers, missing tests, contract mismatches,
and drift from tracked docs. Do not add implementation work unless explicitly
requested, and do not broaden review into feature-scope changes. Keep tracked
docs and release artifacts synchronized with the job record.
<!-- AUDIAGENTIC:END ag-review/doctrine -->

<!-- AUDIAGENTIC:BEGIN agent-jobs/canonical-rule -->
# Canonical workflow tags

Canonical tags (route the raw tagged prompt through the repo-owned bridge):

- `ag-implement` (aliases: `agi`, `i`)
- `ag-plan` (aliases: `agp`, `p`)
- `ag-review` (aliases: `agr`, `r`)

Definitions are managed in `config/components/optional/agent-jobs/tags/`; run `python -m audiagentic.components.optional.providers.skill_surfaces --project-root .` after adding, removing, or renaming tags.
<!-- AUDIAGENTIC:END agent-jobs/canonical-rule -->

<!-- AUDIAGENTIC:BEGIN agent-jobs/prompt-tags -->
# Prompt tag doctrine

- First non-empty line is the routing tag; remaining lines are the raw prompt body.
- Route tagged prompts through the AUDiaGentic workflow bridge — do not handle inline.
- Keep tag semantics identical to the launch contract; do not invent aliases.
- Preserve raw prompt text and provenance: provider-id, surface, session-id survive normalization.
<!-- AUDIAGENTIC:END agent-jobs/prompt-tags -->

<!-- AUDIAGENTIC:BEGIN agent-ledger/process -->
# Agent ledger process

After substantive implementation work, record a change event with the ag-ledger
MCP tool record_change_event — the ledger is the authoritative release record.
Required fields: change-class, files, technical-summary, user-summary-candidate,
status ('unreleased'). Other fields are auto-generated.
- Check release ledger state before changing release notes, changelog fragments, or release workflow files.
- Keep release artifacts and job records synchronized with implementation and review outcomes.
- Do not bypass ledger updates by editing generated release outputs only.
<!-- AUDIAGENTIC:END agent-ledger/process -->

<!-- AUDIAGENTIC:BEGIN coding-lsp/usage -->
# Code intelligence via LSP

The coding-lsp component provides language server protocol tools for code intelligence.
Use LSP tools instead of text search when doing symbol lookup, go-to-definition,
hover documentation, or finding all references — they are more precise.

Available tools (ag-lsp server):
- `lsp_symbols` — search workspace symbols by name
- `lsp_definition` — go to definition at file:line:column
- `lsp_hover` — type and documentation at a position
- `lsp_references` — all references to a symbol
- `lsp_doc_symbols` — file symbol outline
- `lsp_diagnostics` — type errors and warnings
- `lsp_rename_preview` — preview rename refactor

Position format for all tools: "line:column" (1-based).
These tools only operate on languages configured in .coding-lsp/lsp.json.
Use `lsp_config_status` (ag-lsp-mgmt server) to check which languages are active.
<!-- AUDIAGENTIC:END coding-lsp/usage -->

<!-- AUDIAGENTIC:BEGIN release/doctrine -->
# Release doctrine

Use the configured release manager for versioning and publication.
Do not edit generated release artifacts (CHANGELOG.md, RELEASE_NOTES.md) directly.
Run finalize_release only after ledger audit review is complete.
The ledger is archived as part of finalization — this cannot be undone.
<!-- AUDIAGENTIC:END release/doctrine -->

<!-- AUDIAGENTIC:BEGIN source-control/doctrine -->
# Source control doctrine

Do not invoke git or GitHub APIs directly — use the MCP tools.
<!-- AUDIAGENTIC:END source-control/doctrine -->
