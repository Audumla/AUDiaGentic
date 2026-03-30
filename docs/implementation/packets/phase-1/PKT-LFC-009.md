# PKT-LFC-009 — Lifecycle updates for prompt-launch policy fields

**Phase:** Phase 1.2  
**Primary owner group:** Lifecycle

## Goal

Extend lifecycle validation and config preservation so `.audiagentic/project.yaml` can safely carry prompt-launch policy and workflow override fields.

## Why this packet exists now

The .2 extension adds tracked config that must survive fresh install, update, cutover, and validation operations. Without a lifecycle packet, those fields could be dropped or rejected even if the jobs layer implements prompt launch correctly.

## Dependencies

- Phase 1 gate `VERIFIED`
- `PKT-FND-009`

## Concrete lifecycle inputs

This packet must recognize and preserve:

- `workflow-overrides`
- `prompt-launch.syntax`
- `prompt-launch.allow-adhoc-target`
- `prompt-launch.default-review-policy.required-reviews`
- `prompt-launch.default-review-policy.aggregation-rule`
- `prompt-launch.default-review-policy.require-distinct-reviewers`

## Ownership boundary

This packet owns the following implementation surface:

- `src/audiagentic/lifecycle/*`
- lifecycle tests under `tests/unit/lifecycle/` and `tests/e2e/lifecycle/`
- example scaffold yaml generation if lifecycle owns it in code

### It may read from
- updated `project-config` schema from `PKT-FND-009`
- example scaffold docs

### It must not edit directly
- contract schemas
- release core
- jobs core
- provider modules

## Detailed build steps

1. Update lifecycle validation to accept the new `.audiagentic/project.yaml` fields.
2. Ensure fresh install preserves or writes deterministic defaults for allowed fields.
3. Ensure update/cutover operations do not drop valid prompt-launch policy fields.
4. Ensure uninstall behavior continues to preserve tracked docs by policy.
5. Add tests proving round-trip preservation of the new fields.

## Tests to add or update

- lifecycle validation tests with prompt-launch policy fields
- fresh install/update tests proving field preservation

## Acceptance criteria

- lifecycle accepts valid prompt-launch policy fields
- lifecycle rejects invalid prompt-launch policy values
- valid `.audiagentic/project.yaml` content survives lifecycle operations
- no new tracked config file is introduced for workflows in MVP

## Recovery procedure

If this packet fails mid-implementation:
- revert lifecycle changes
- rerun `python -m pytest tests/unit/lifecycle tests/e2e/lifecycle`

## Parallelization note

This packet may run in parallel only with work that does not modify lifecycle modules.

## Out of scope

- schema changes
- prompt parsing or launch behavior
- review aggregation behavior
