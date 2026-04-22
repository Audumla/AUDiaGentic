---
id: task-357
label: Freeze regression matrix and evidence expectations
state: draft
summary: Define smoke, focused, and broader regression expectations for CLI, reconciliation, migration, and artifact paths.
spec_ref: spec-84
request_refs:
- request-32
standard_refs:
- standard-4
- standard-5
- standard-6
---

# Description

State what must be proven before implementation packets or later imports are accepted.

# Inputs

Read before starting:
- `docs/installer/fixture-catalog.md` (output from task-356)
- `spec-84` — regression foundation spec

# Spec consistency check

Before finalizing the regression matrix, check that:
- `spec-81` architecture constraints
- `spec-82` resolution and validation rules
- `spec-83` target/backend model
- `spec-84` packetization and regression rules

do not conflict in ways that would make verification impossible or ambiguous.

If a conflict exists, add a `Spec consistency blockers` section to the output with:
- conflicting IDs
- conflicting statements
- impact on verification design
- recommended resolution order
- `src/audiagentic/tests/` — existing test modules
- `tools/validation/` — existing validation tools
- `standard-4` — review findings and evidence standard
- `standard-5` — verification and test evidence standard

# Output

Produce `docs/installer/regression-matrix.md` with these sections:

## Smoke checks

For each smoke check, document:
- Check name
- What it validates (CLI parsing, basic resolution, etc.)
- Fixture used
- Expected pass criteria
- Execution time budget (e.g., < 5 seconds)

## Focused integration checks

For each focused integration check, document:
- Check name
- What it validates (CLI + resolution, resolution + backend, etc.)
- Fixtures used
- Expected pass criteria
- Execution time budget (e.g., < 30 seconds)

## Slower upgrade or artifact checks

For each slower check, document:
- Check name
- What it validates (upgrade path, artifact application, etc.)
- Fixtures used
- Expected pass criteria
- Execution time budget (e.g., < 5 minutes)

## Evidence expectations for packet closure

For each implementation packet, document:
- Required smoke checks (must all pass)
- Required focused integration checks (must all pass)
- Required slower checks (if applicable)
- Evidence format (test output, log file, etc.)
- Who reviews the evidence (implementor, reviewer, both)

# What not to change

- do not define new fixture targets (belongs in task-356)
- do not define packet boundaries (belongs in task-358)
- do not change the spec consistency check requirement from wp-31
- do not claim any check is runnable before the fixtures from task-356 exist

# Acceptance criteria

- [ ] smoke checks are documented with name, validation target, fixture, pass criteria, and time budget
- [ ] focused integration checks are documented with name, validation target, fixtures, pass criteria, and time budget
- [ ] slower upgrade/artifact checks are documented with name, validation target, fixtures, pass criteria, and time budget
- [ ] evidence expectations specify required checks per packet type, evidence format, and reviewer
- [ ] verification depth is proportional to risk (higher risk = more checks)
- [ ] unverified areas are explicitly named (no silent gaps)
- [ ] reviewer can verify by checking that each check references a fixture from task-356 output
