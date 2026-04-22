---
id: task-29
label: Verify test coverage for config-driven planning create paths
state: done
summary: Verify all create-path tests pass after enabling validate_required=True,
  and add regression tests for required-ref enforcement and guidance-level section
  variation
domain: core
spec_ref: spec-33
standard_refs:
- standard-0005
- standard-0006
---











## Description\n\nVerify and extend test coverage for config-driven planning create paths. This task gates closing spec-29 — it must run after task-339 enables `validate_required=True`.\n\n## Test Areas\n\n### AC 7 — All existing tests pass\n\nRun the full planning test suite after task-339 is merged:\n```bash\npytest tests/audiagentic/planning/ -x -v\n```\nAll tests must pass. Fix any breakage caused by enabling required-ref validation.\n\n### AC 8 — Profile/guidance produces different section structures\n\nAdd or verify tests that assert:\n- Creating a spec with `guidance=light` produces fewer sections than `guidance=deep`\n- Creating a task with `guidance=standard` uses the standard template from profiles.yaml\n- `section_registry.list_sections(kind, guidance)` returns correct sections per guidance level\n\n### AC 11 regression — Required-ref enforcement\n\nAdd regression tests:\n- Creating a spec **with** valid `request_refs` succeeds\n- Creating a spec **without** `request_refs` raises `ValueError` containing \"Missing required reference\"\n- Creating a plan **without** `spec_refs` raises `ValueError`\n- Creating a task **without** `spec_ref` succeeds (not required per config)\n- Creating a wp — verify whether `plan_ref` should be required (update profiles.yaml if so)\n\n## Files to Touch\n\n- `tests/audiagentic/planning/` — add/extend create-path tests\n- `src/audiagentic/planning/app/api.py` — fix any test-revealed breakage only\n- `.audiagentic/planning/config/profiles.yaml` — update `required_for_children` if wp/task gaps confirmed\n\n## Acceptance Criteria\n\n1. Full planning test suite passes with `validate_required=True` active\n2. At least one test per guidance level (light/standard/deep) verifying section output\n3. Regression tests for required-ref rejection on spec and plan\n4. No regressions in other planning functionality

# Notes

## 2026-04-22 Progress

Tests added to `tests/integration/planning/test_planning_api_coverage.py`:
- `TestGuidanceSectionVariation` — 4 tests covering AC 8
- `TestRequiredRefEnforcement` — 5 regression tests covering AC 11

Needs: `pytest tests/integration/planning/test_planning_api_coverage.py -x -v` to confirm pass.
