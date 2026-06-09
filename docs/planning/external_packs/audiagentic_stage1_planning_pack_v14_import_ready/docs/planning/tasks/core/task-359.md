---
id: task-359
label: Freeze component lifecycle manifest schema
state: draft
summary: Survey the knowledge component as a reference case, validate the manifest schema from spec-85 against it, and produce the canonical component lifecycle manifest document.
spec_ref: spec-85
request_refs:
- request-32
standard_refs:
- standard-6
- standard-8
- standard-11
---

# Description

Ground the manifest schema in a real component before freezing it. Use the knowledge component as the reference case. Produce a canonical manifest document that later tasks and backend implementors can rely on without reopening schema questions.

# Inputs

Read before starting:

- `spec-85` — component lifecycle manifest schema and semantics
- `docs/installer/current-state-inventory.md` (output from task-347) — ownership boundaries
- `docs/installer/registry-ownership-matrix.md` (output from task-349) — registry ownership decisions
- `.audiagentic/knowledge/config/config.yml` — knowledge component config structure
- `src/audiagentic/knowledge/__init__.py` — knowledge event subscription entry point
- `src/audiagentic/planning/app/api.py` lines 78-86 — where knowledge is wired into planning
- `.audiagentic/interoperability/config.yaml` — event bus config

# Output

Produce `docs/installer/component-lifecycle-manifest.md` with these sections:

## Schema definition

Document the canonical manifest schema fields with types, required/optional status, and allowed values. Mirror the schema from spec-85 and note any corrections discovered during survey.

## Knowledge component reference manifest

Write a complete, validated manifest entry for the knowledge component using the schema above. Every field must be populated or explicitly set to null with a reason. This manifest must be verified against the live repo — do not invent values.

For each field, document:

- populated value
- source (which file or line confirmed it)
- whether the value would change if knowledge is replaced by a 3rd-party

## Replacement slot pattern

Document the `replaces` field semantics and show a skeleton manifest for a hypothetical `knowledge-external` component using the same event subscription patterns.

## Schema validation rules

For each required field, document the validation rule:

- type constraint
- allowed values
- what a missing or malformed value means for the reconcile flow

## Blockers and drift

If the live knowledge component does not match manifest assumptions:

- document the discrepancy
- propose schema adjustment if needed
- flag as blocker if the discrepancy prevents schema validation

# What not to change

- do not define backend execution behavior (this task freezes schema only)
- do not modify any source files in `src/audiagentic/`
- do not modify any `.audiagentic/` config files
- do not define which components exist beyond the knowledge reference case
- do not define CLI flag behavior (belongs in task-360)
- do not add manifest fields not present in spec-85 without recording them as proposed additions

# Blocker handling

- the knowledge component is part of the core package and does not self-register via `importlib.metadata` entry points — record this as a known gap in the manifest survey. The `entry_point` field should be set to null for knowledge and this gap flagged for resolution in a future task
- if `src/audiagentic/knowledge/__init__.py` does not expose a clear subscription entry point, record the actual wiring and propose a manifest field adjustment
- if event subscription patterns cannot be determined from the live repo, mark `owns.event_subscriptions` as TBD and flag as a blocker
- if `docs/installer/registry-ownership-matrix.md` is not yet complete, record the dependency and continue with schema validation using spec-85 alone

# Acceptance criteria

- [ ] schema definition covers all fields from spec-85 with types and allowed values
- [ ] knowledge component reference manifest is complete and every value is sourced to a live file
- [ ] replacement slot pattern is documented with a skeleton manifest
- [ ] schema validation rules cover all required fields
- [ ] any schema corrections discovered during survey are recorded as proposed adjustments with justification
- [ ] `Blockers and drift` section is present even if empty
- [ ] reviewer can cross-reference every manifest value against the cited source file
