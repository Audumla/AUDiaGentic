# PKT-FND-009 — Prompt launch + review bundle contracts and schemas

**Phase:** Phase 0.2  
**Primary owner group:** Contracts

## Goal

Finalize the additive contract/schema/fixture work required by the .2 prompt-launch and structured-review extension while keeping Phase 0 validation guarantees intact.

## Why this packet exists now

The preserved prompt-launch draft did not define enough machine-readable contract detail to let multiple implementors work safely. This packet freezes those shapes before the jobs layer changes.

## Dependencies

- Phase 0 gate `VERIFIED`
- `PKT-FND-008`
- `PKT-PRV-012`

## Concrete contract inputs

This packet must finalize:

- `ProjectConfig.workflow-overrides`
- `ProjectConfig.prompt-launch`
- `PromptLaunchRequest`
- `ReviewReport`
- `ReviewBundle`
- additive JobRecord fields for launch/review metadata
- additive ChangeEvent source fields for prompt/review provenance

## Ownership boundary

This packet owns the following implementation surface:

- `docs/specifications/architecture/03_Common_Contracts.md`
- `docs/specifications/architecture/26_Prompt_Tagged_Workflow_Launch_and_Review_Extension.md`
- `src/audiagentic/contracts/schemas/project-config.schema.json`
- `src/audiagentic/contracts/schemas/job-record.schema.json`
- `src/audiagentic/contracts/schemas/change-event.schema.json`
- `src/audiagentic/contracts/schemas/prompt-launch-request.schema.json`
- `src/audiagentic/contracts/schemas/review-report.schema.json`
- `src/audiagentic/contracts/schemas/review-bundle.schema.json`
- new fixtures under `docs/examples/fixtures/`
- `tools/validate_schemas.py`
- `tests/unit/contracts/test_schema_validation.py`

### It may read from
- `PKT-PRV-012` outputs for provider/model field names
- the preserved prompt-launch draft
- current schema validation tooling

### It must not edit directly
- lifecycle, release, jobs, providers, or overlay modules
- tracked release docs outside the release ownership boundary

## Detailed build steps

1. Freeze additive fields in `03_Common_Contracts.md`.
2. Add or update schemas for project config, job record, and change event.
3. Add new schemas for prompt launch and review artifacts.
4. Add valid and invalid fixtures for every new schema.
5. Ensure fixtures cover `target.kind=adhoc` and duplicate reviewer cases.
6. Update schema validation tooling if the new schema family requires registration.
7. Run schema validation tests and verify fixture coverage.

## Tests to add or update

- `tests/unit/contracts/test_schema_validation.py`

Minimum fixture set:
- `prompt-launch-request.valid.json`
- `prompt-launch-request.invalid.json`
- `review-report.valid.json`
- `review-report.invalid.json`
- `review-bundle.valid.json`
- `review-bundle.invalid.json`
- additive `project-config` valid/invalid cases

## Acceptance criteria

- all new schemas validate in CI
- additive contract fields are documented
- no behavior modules are changed outside contract ownership
- schemas remain additive and do not invalidate existing valid fixtures

## Recovery procedure

If this packet fails mid-implementation:
- revert edited contract docs and schemas
- delete new fixtures added for the .2 extension
- rerun `python -m pytest tests/unit/contracts/test_schema_validation.py`

## Parallelization note

This packet blocks any other packet touching shared contracts or schemas.

## Out of scope

- parser implementation
- lifecycle behavior
- release behavior
- job execution behavior
