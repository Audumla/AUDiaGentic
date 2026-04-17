---
id: spec-5
label: Canonical planning filename and maintenance reconciliation
state: draft
summary: Define config-driven canonical planning filenames, reference repair, and
  one maintenance path for reconcile plus rebuild of derived planning state
request_refs:
- request-31
task_refs: []
standard_refs:
- standard-0006
- standard-0005
---



# Purpose

Define one canonical, config-driven filename convention for planning objects and one canonical maintenance path that reconciles filenames, repairs references, and rebuilds derived planning state.

# Scope

- Define canonical filename convention for planning objects
- Store naming convention in planning config
- Apply same convention to create and reconcile flows
- Repair references when filenames are reconciled
- Expose one canonical maintenance/rebuild path in planning API/MCP
- Rebuild indexes/extracts/derived planning state after repair

Out of scope:
- introducing new planning object kinds
- changing planning semantic relationships unrelated to naming/references

# Requirements
## Canonical Naming

- Naming convention must be defined in planning config, not only in code.
- Config should clearly capture:
  - numeric formatting policy
  - slug inclusion policy
  - canonical filename pattern shape
  - any narrow legacy exceptions, if they must exist
- Canonical pattern should be sortable and human-readable.
- Create and reconcile flows must read the same config-owned naming rule.

## Reference Repair

Reconciliation must update or preserve resolution for:
- planning frontmatter refs such as `request_refs`, `spec_ref`, `plan_ref`, `task_refs`, `parent_task_ref`, `standard_refs`
- indexes and lookup artifacts
- generated artifacts or docs that depend on planning file paths where applicable
- any maintenance outputs that would otherwise keep stale file paths

## Maintenance Path

There should be one canonical planning maintenance entry point that orchestrates:
- filename reconciliation
- reference repair
- derived index rebuild
- extract/cache cleanup or rebuild
- final validation/verification

Other maintenance flows should delegate to this path rather than duplicating rebuild logic.

## API / MCP Surface

Planning API should expose one canonical maintenance method.
Planning MCP/admin should expose one corresponding operation rather than relying on manual fs cleanup.
If existing reindex or reconcile operations remain, their behavior should delegate to or align with the canonical maintenance path.

## Migration Semantics

The system must support safe reconciliation of already-mixed planning artifacts in repo.
Migration should not leave stale lookup state or unresolved references after renames.
# Constraints

- Preserve planning IDs and object semantics safely
- Do not leave stale derived state after reconciliation
- Keep naming convention centralized in config, not scattered across code
- Avoid multiple competing cleanup/rebuild code paths

# Acceptance Criteria
1. Naming convention is documented clearly and stored in config.
2. New planning objects use canonical filenames automatically.
3. Reconcile/repair path applies canonical naming consistently to legacy mixed-format files.
4. Reference repair is part of reconciliation, not a manual follow-up.
5. One canonical maintenance API/MCP path rebuilds derived planning state.
6. Existing reindex/reconcile behaviors either delegate to or remain consistent with the canonical maintenance path.
7. Indexes/lookups/extracts validate cleanly after repair.
8. Tests cover filename generation, migration/reconciliation, reference repair, and rebuild behavior.
