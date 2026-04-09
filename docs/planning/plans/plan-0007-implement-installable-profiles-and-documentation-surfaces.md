---
id: plan-0007
label: Implement installable profiles and documentation surfaces
state: done
summary: Deliver an implementation-ready plan for installable profile packs, documentation
  surfaces, references docs, manifest scaffolding, and MCP expansion.
spec_refs:
- spec-0021
work_package_refs:
- ref: wp-0005
  seq: 1000
  display: '1'
- ref: wp-0006
  seq: 2000
  display: '2'
- ref: wp-0007
  seq: 3000
  display: '3'
---






# Objectives

Ship a branch-aligned delta that extends the planning component without changing the core planning hierarchy or violating the template installation contract.

# Delivery Approach

Work in three packages:
1. Config, profile-pack, docs, and manifest scaffolding
2. MCP/API expansion and section navigation notes
3. Supporting docs, subsection access, and doc-sync obligations

# Dependencies

- existing planning-module-implementation branch structure
- existing schemas/config split
- existing MCP server entrypoint
- architecture docs 12 and 50
- current planning validator/indexer behavior

# Tracks

- config and schema
- docs and references
- MCP and API
- install/migration scaffolding
- supporting docs and doc sync
- validation and tests


# Implementation Approach

Implement this delta in staged layers so configuration and validation land before helper and MCP expansion.

Stage 1: configuration and schema foundation.
- confirm the shipped planning config files are optional where intended
- keep profile packs, request profiles, and documentation surfaces as distinct concepts
- ensure schema and runtime models agree on every field used in config, including `seed_on_install`

Stage 2: helper and MCP read surfaces.
- expose documentation surfaces, request profiles, reference docs, support docs, and doc-sync queries through the planning helper and MCP
- keep this stage read-focused except where existing planning APIs already support safe section updates
- keep subsection navigation explicitly best-effort and heading-based in this phase

Stage 3: verification and documentation hardening.
- add focused tests for config loading, helper queries, subsection navigation, and verify-structure behavior
- align references docs and MCP guidance with the actual runtime behavior
- confirm the planning pack remains template-safe and does not imply installer behavior

# Sequencing

Recommended execution order:
1. `task-0181` documentation surfaces
2. `task-0182` profile packs and request profiles
3. `task-0183` reference docs
4. `task-0184` manifest and migration scaffolding boundaries
5. `task-0185` helper and MCP expansion
6. `task-0186` section registry and subsection limits
7. `task-0187` supporting-doc metadata and sidecar behavior
8. `task-0188` documentation-sync obligations and verification coverage

Execution notes:
- complete the config and schema work before helper/MCP exposure
- complete helper/MCP exposure before widening verification expectations
- do not treat support docs as first-class planning kinds in this phase

# Risk Assessment

Primary risks:
- profile-pack, request-profile, and workflow-profile terminology drifting together and causing implementation overlap
- documentation-surface ownership being underspecified for template installs, especially for `README.md` and `CHANGELOG.md`
- support-doc work quietly widening scan/index/validator behavior beyond the intended phase
- subsection behavior being documented as canonical when it remains heading-based and best-effort
- doc-sync rules implying automatic file mutation when the intended behavior is query-only

Mitigations:
- keep concept boundaries explicit in config, schemas, helper docs, and tasks
- keep ownership modes documented as `manual`, `hybrid`, `managed`, plus `seed_on_install`
- keep support docs sidecar only in this phase
- back helper and MCP claims with focused regression tests

# Current Implementation Status

Already present in the repository:
- planning objects for request, spec, plan, work packages, and tasks in this delta
- planning config and schema scaffolding for documentation surfaces, profile packs, request profiles, and supporting docs
- helper and MCP read/query surfaces for documentation and support-doc capabilities
- focused planning tests covering the integrated config and helper extensions

Still to be treated as implementation work rather than planning prep:
- production use of these planning surfaces in downstream feature work
- any lifecycle or installer behavior beyond documented scaffolding
- any widening of planning object kinds or runtime install ownership enforcement beyond the current planning surface

# Validation Strategy

Minimum verification required before marking this plan execution-complete:
- `python tools/planning/tm.py validate`
- `pytest -q tests/unit/planning/test_config_extensions.py tests/integration/planning/test_planning_config_extensions.py tests/integration/planning/test_tm_helper_extensions.py tests/integration/planning/test_planning_api.py`
- manual verification that helper and MCP docs match actual subsection and doc-sync behavior
- manual verification that no task introduces installer/runtime lifecycle logic under the planning umbrella

Coverage expectations:
- config load and schema validation for optional planning extension files
- helper and MCP smoke coverage for doc surfaces, request profiles, reference docs, support docs, and verify-structure behavior
- subsection-path coverage for documented path formats and missing-path behavior
- doc-sync query coverage for known and unknown profile packs

# Task Tracking

Tracked work packages:
- `wp-0005` covers `task-0181` to `task-0184`
- `wp-0006` covers `task-0185` and `task-0186`
- `wp-0007` covers `task-0187` and `task-0188`

Tracking status:
- all eight tasks are linked from `spec-0021`
- all three work packages are linked from this plan
- the tasks remain in `draft` until the standards-reference issue is resolved and execution is explicitly started

# Pre-Execution Blocker
The missing standards problem for this planning slice has been resolved by adding default standards and linking them into the current planning records.

Remaining caution:
- keep the standards concise and default-oriented rather than treating them as a substitute for project-specific architecture or lifecycle standards
- if future work wants different defaults, update the `standard_refs` intentionally rather than relying on implicit inheritance or missing files
