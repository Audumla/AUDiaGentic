---
id: task-356
label: Freeze fixture catalog and generic regression targets
state: draft
summary: Define fixture targets and regression cases for generic target kinds, extension seams, compatibility failures, and preservation-aware behavior.
spec_ref: spec-84
request_refs:
- request-32
standard_refs:
- standard-4
- standard-5
- standard-6
---

# Description

Make generic-platform behavior testable without live vendor dependencies.

# Inputs

Read before starting:
- `docs/installer/apply-boundaries.md` (output from task-355)
- `spec-84` — regression foundation spec
- `src/audiagentic/tests/fixtures/` — existing fixture modules (if any)
- `tools/validation/` — existing validation tools
- `standard-4` — review findings and evidence standard
- `standard-5` — verification and test evidence standard

# Output

Produce `docs/installer/fixture-catalog.md` with these sections:

## Fixture inventory

For each fixture, document:
- Fixture name (exact identifier)
- Fixture type (config file, registry state, target definition, artifact)
- What it represents (real-world scenario, edge case, backward-compat case)
- File path (where fixture data lives)
- Offline-safe (yes/no — does it require live vendor dependencies?)

## Target-kind coverage

For each target kind, document:
- Target kind name
- Which fixtures cover it
- What behavior is tested (apply, plan, validate, doctor)
- Coverage gap (if any fixtures are missing)

## Compatibility-failure coverage

For each compatibility failure scenario, document:
- Scenario name
- Fixture that triggers it
- Expected error category (compatibility_failure, malformed_input, etc.)
- Expected error message format
- Test that validates the error

## Preservation and migration coverage

For each preservation/migration scenario, document:
- Scenario name
- Fixture that triggers it
- Expected preservation behavior (what is preserved, what is migrated)
- Expected migration function call (module path)
- Test that validates the behavior

# What not to change

- do not introduce fixtures that require live vendor dependencies (all must be offline-safe)
- do not modify existing fixture modules in `src/audiagentic/tests/fixtures/`
- do not modify existing validation tools in `tools/validation/`
- do not add fixture types beyond the four listed (config file, registry state, target definition, artifact)
- do not change expected error categories from those defined in task-352
- do not change expected migration function calls without spec-82 approval
- do not remove existing fixtures

# Acceptance criteria

- [ ] fixture inventory lists all fixtures with type, representation, file path, and offline-safe status
- [ ] each target kind has at least one covering fixture
- [ ] each compatibility failure category has at least one test fixture
- [ ] each preservation/migration scenario has a fixture and expected behavior
- [ ] all fixtures are offline-safe (no live vendor dependencies)
- [ ] reviewer can verify by checking that each fixture file path exists or is a valid new path
