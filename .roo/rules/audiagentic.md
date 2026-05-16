<!-- AUDIAGENTIC:BEGIN agent-jobs/canonical-rule -->
# Canonical workflow tags

Canonical tags:

- `@ag-plan`
- `@ag-implement`
- `@ag-review`
- `@ag-audit`
- `@ag-check-in-prep`

Rules:

- Do not reinterpret these tags — route the raw tagged prompt through the repo-owned bridge.
- Keep tag semantics identical to the shared AUDiaGentic launch contract.
- Keep provenance visible: provider id, surface, and session id should survive normalization.
- Canonical names are config-managed in `.audiagentic/config/execution/prompt-syntax.yaml`;
  run `python tools/regenerate_tag_surfaces.py --project-root .` after renaming tags or aliases.
<!-- AUDIAGENTIC:END agent-jobs/canonical-rule -->

<!-- AUDIAGENTIC:BEGIN agent-jobs/planning-item-policy -->
# Planning item creation policy

Planning items (requests, specs, plans, tasks) can only be created with explicit user approval.

- Do not autonomously create planning items during analysis, review, or exploration work.
- If analysis suggests a new request or spec is needed, report findings and ask for approval.
- Use the canonical tags (`@ag-plan`) to signal planning work that requires user direction.
- Only create planning items in response to explicit user instruction or approved workflow prompts.
<!-- AUDIAGENTIC:END agent-jobs/planning-item-policy -->

<!-- AUDIAGENTIC:BEGIN agent-jobs/review-doctrine -->
# Review doctrine

- Review prompts should stay read-focused unless the normalized request explicitly allows more.
- Do not broaden review into implementation work.
- Keep tracked docs and release artifacts synchronized with the job record.
<!-- AUDIAGENTIC:END agent-jobs/review-doctrine -->

<!-- AUDIAGENTIC:BEGIN agent-jobs/tag-shortcuts -->
# Tag shortcuts and aliases

Tag and provider aliases are centralized in `.audiagentic/config/execution/prompt-syntax.yaml`
and work in all surfaces.

Tag aliases:

- `agp` -> `ag-plan`
- `agi` -> `ag-implement`
- `agr` -> `ag-review`
- `aga` -> `ag-audit`
- `agc` -> `ag-check-in-prep`

Provider aliases:

- `cx` -> `codex`
- `cld` -> `claude`
- `cln` -> `cline`
- `gm` -> `gemini`
- `opc` -> `opencode`
- `cp` -> `copilot`

All of these are equivalent:

```text
@ag-review provider=cline
@agr provider=cline
@review provider=cline
@r provider=cline
@ag-review-cline
@r-cline
```
<!-- AUDIAGENTIC:END agent-jobs/tag-shortcuts -->

<!-- AUDIAGENTIC:BEGIN release-audit-ledger.process -->
# Release audit ledger process

For release-affecting work, follow AUDiaGentic release ledger process.

- Check release ledger state before changing release notes, changelog fragments, or release workflow files.
- Keep release artifacts and job records synchronized with implementation and review outcomes.
- Add or update the release ledger fragment when behavior, public workflow, or generated release output changes.
- Do not bypass ledger updates by editing generated release outputs only.
<!-- AUDIAGENTIC:END release-audit-ledger.process -->
