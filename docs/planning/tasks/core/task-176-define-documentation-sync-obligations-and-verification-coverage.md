---
id: task-176
label: Define documentation-sync obligations and verification coverage
state: done
summary: Review documentation-sync rules, ownership impacts, and the validation/test
  coverage needed before implementation
spec_ref: spec-5
---








# Description

Review the documentation-sync obligation model so it is queryable, template-safe, and covered by validation and tests before implementation begins.

**Status: IMPLEMENTED**

All implementation work for task-0176 is complete:
- Doc-sync rules are queryable without auto-editing project docs
- Profile packs define required_updates per work kind:
  - minimal: task=[changelog], wp=[changelog]
  - standard: task=[changelog], wp=[changelog, readme]
  - full_project: task=[changelog], wp=[changelog, readme, references_index]
  - audiagentic_full: task=[changelog], wp=[changelog, readme, references_index]
- Helper functions: get_doc_sync_requirements(), pending_doc_updates()
- _validate_profile_pack() fails clearly for unknown profile-pack ids
- Tests verify:
  - get_doc_sync_requirements() returns correct required_updates for "task" kind
  - pending_doc_updates() returns correct list for "wp" kind
  - Unknown profile packs raise ValueError with clear message
- Docs in planning-doc-sync.md and planning-verification-matrix.md document query-only behavior
- Doc-sync interacts with manual/hybrid/managed ownership modes and seed_on_install
- Verification matrix ties doc-sync to explicit tests rather than prose-only promises
- Junior implementer can identify which config files define obligations

# Acceptance Criteria

1. The task identifies which work kinds trigger required updates for which documentation surfaces.
2. The task explains how required doc updates interact with manual/hybrid/managed ownership and seed-on-install behavior files.
3. The task records the missing unit, contract, and smoke tests needed for confidence.
4. The task updates the review notes and feature list so the pack no longer claims unsupported completeness.
5. The task ties verification to an explicit matrix rather than prose-only promises.

# Notes

- Suitable with revision.
- The pack introduces useful `required_updates` examples, but it does not yet show how compliance will be validated or how this behaves in projects that own their own docs.
- The pack also claims tests in places where none are included.

# Implementation Notes

- Add a verification matrix for config validation, planning validation, and MCP smoke coverage.
- Keep doc-sync rules queryable without forcing automatic file mutation.
- Ensure the final wording matches the template installation contract.


# Execution Checklist

Implementation type: query behavior + config examples + tests + docs.

Files to change:
- `.audiagentic/planning/config/profile-packs/minimal.yaml`
- `.audiagentic/planning/config/profile-packs/standard.yaml`
- `.audiagentic/planning/config/profile-packs/full_project.yaml`
- `.audiagentic/planning/config/profile-packs/audiagentic_full.yaml`
- `src/audiagentic/planning/app/docs_mgr.py`
- `tools/planning/tm_helper.py`
- `docs/references/planning/planning-doc-sync.md`
- `docs/references/planning/planning-verification-matrix.md`
- `tests/integration/planning/test_tm_helper_extensions.py`

Steps:
1. Keep doc-sync queryable without auto-editing project docs.
2. Define `required_updates` per work kind in the shipped profile packs.
3. Ensure helper methods fail clearly for unknown profile-pack ids.
4. Add tests for non-empty doc-sync results on a known pack and clear failure on an unknown pack.
5. Document how doc-sync interacts with `manual`, `hybrid`, `managed`, and `seed_on_install` surfaces.

Do not change:
- release completion or task completion rules to auto-mutate docs
- project docs directly as part of doc-sync queries
- lifecycle/install ownership code outside the planning surface

Verification:
- `pytest -q tests/integration/planning/test_tm_helper_extensions.py`
- `python tools/planning/tm.py validate`
- manually confirm known pack queries return expected surfaces such as `changelog`

Done means:
- doc-sync behavior is explicit, query-only, and tested
- unknown pack handling is clear
- a junior implementer can tell exactly which config files define the obligations
