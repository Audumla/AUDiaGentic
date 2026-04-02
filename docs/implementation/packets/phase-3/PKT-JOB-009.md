# PKT-JOB-009 — Structured review loop + multi-review aggregation

**Phase:** Phase 3.2  
**Primary owner group:** Jobs

## Goal

Implement structured review reports, review bundle aggregation, and deterministic review-gated progression so implementation or plan work can be reviewed by multiple agents before check-in/approval progression.

## Why this packet exists now

Prompt launch alone is not enough. The original requirement also called for a review phase where an implementation or plan can be checked by multiple agents before being committed. This packet makes review a first-class, testable workflow behavior.

## Dependencies

- `PKT-JOB-008`
- `PKT-RLS-010`

## Concrete inputs

This packet must support:

- `ReviewReport` creation from `@review` prompts
- `ReviewBundle` aggregation for multiple reviews
- default review policy loaded from `.audiagentic/project.yaml`
- `required-reviews`
- `aggregation-rule=all-pass`
- `require-distinct-reviewers=true`
- review subjects of kind `artifact`, `job`, `packet`, or `adhoc`

## Ownership boundary

This packet owns the following implementation surface:

- `src/audiagentic/execution/jobs/reviews.py`
- additive updates in `src/audiagentic/execution/jobs/stages.py`
- additive updates in `src/audiagentic/execution/jobs/records.py`
- additive updates in `src/audiagentic/execution/jobs/store.py`
- review tests under `tests/unit/jobs/` and `tests/integration/jobs/`

### It may read from
- approval/event contracts
- release omission rules from `PKT-RLS-010`
- prompt launch artifacts created by `PKT-JOB-008`

### It must not edit directly
- provider adapters
- release core ownership files beyond agreed integration seams
- lifecycle modules
- tracked release docs

## Detailed build steps

1. Implement review report persistence under the owning job runtime path.
2. Implement review bundle creation/update logic.
3. Enforce distinct reviewer counting when policy requires it.
4. Implement deterministic `all-pass` aggregation.
5. Update stage handling so review progression is blocked when the bundle decision is `rework` or `blocked`.
6. Expose review outcome metadata without writing raw review content into tracked docs.
7. Add tests for repeated review after fixes and conflicting review outcomes.

## Required runtime artifacts

This packet must write runtime artifacts such as:

- `.audiagentic/runtime/jobs/<job-id>/reviews/review-report.<review-id>.json`
- `.audiagentic/runtime/jobs/<job-id>/reviews/review-bundle.json`

## Integration points

- `src/audiagentic/execution/jobs/approvals.py`
- `src/audiagentic/execution/jobs/stages.py`
- `src/audiagentic/execution/jobs/release_bridge.py`
- `docs/specifications/architecture/14_Approval_Core_and_Event_Model.md`

## Tests to add or update

- `tests/unit/jobs/test_review_aggregation.py`
- `tests/integration/jobs/test_review_loop.py`

Minimum cases:
- single review produces report
- two distinct reviews produce approved bundle when both pass
- duplicate reviewer does not count twice
- any `rework` causes bundle decision `rework`
- any `block` causes bundle decision `blocked`
- fixed artifact can be re-reviewed and move bundle to `approved`

## Acceptance criteria

- review reports are structured and schema-valid
- review bundles aggregate deterministically
- multiple reviewers can gate progression before commit/check-in work
- raw review content stays runtime-only unless later surfaced intentionally
- repeated review after fixes is supported and testable

## Recovery procedure

If this packet fails mid-implementation:
- revert `src/audiagentic/execution/jobs/reviews.py` and additive job edits
- delete partial runtime review artifacts under `.audiagentic/runtime/jobs/*/reviews/`
- rerun `python -m pytest tests/unit/jobs/test_review_aggregation.py tests/integration/jobs/test_review_loop.py`

## Parallelization note

This packet may run only after `PKT-JOB-008` is verified and only with work that does not touch shared job modules.

## Out of scope

- automatic reviewer assignment
- majority-pass voting
- automatic merge/commit execution
