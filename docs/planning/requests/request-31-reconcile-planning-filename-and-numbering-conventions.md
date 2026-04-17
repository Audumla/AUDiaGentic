---
id: request-31
label: Reconcile planning filename and numbering conventions
state: captured
summary: Define and enforce one canonical filename pattern for planning objects, including
  consistent numeric formatting and slugs, then reconcile existing mixed-format artifacts
source: codex
guidance: standard
current_understanding: Initial intake captured; requirements are understood well enough
  to proceed.
open_questions:
- What exact outcome is required?
- What constraints or non-goals apply?
- How will success be verified?
standard_refs:
- standard-0001
spec_refs:
- spec-5
---







# Understanding

Planning artifacts now use inconsistent filename and numeric formatting.

Observed examples:
- requests: `request-1.md` and `request-30.md`
- specs: `spec-020-planning-state-propagation-over-events-specification.md` and `spec-4-compact-planning-config-discovery-for-agents.md`
- tasks: `task-0012.md` and `task-12.md`

This means ID formatting, counter behavior, and filename conventions are not being enforced consistently across planning objects.

# Problem

Planning object numbering and filename patterns need reconciliation.

Current shortcomings:
1. Mixed zero-padded and non-padded numeric IDs in filenames.
2. Some files use slugged filenames while others use bare IDs only.
3. Counter and creation behavior appear inconsistent across kinds and over time.
4. Filename inconsistency makes planning artifacts harder to scan, sort, and automate against.
5. The system lacks one clearly enforced canonical filename pattern.

# Desired Outcome

Define and enforce one canonical filename pattern across planning objects, then reconcile existing artifacts.

Observable outcomes:
1. Requests, specs, tasks, plans, wps, and standards all follow one numeric formatting rule.
2. All planning object filenames include a slug consistently.
3. Creation/update flows produce canonical filenames automatically.
4. Existing planning objects are reconciled or migrated safely to the canonical pattern.
5. Indexing, lookup, and cross-reference behavior continue to work after reconciliation.

# Constraints

- Preserve object IDs and references safely during reconciliation.
- Avoid breaking existing planning lookup and MCP/API behavior.
- Canonical pattern should be sortable and human-readable.
- Migration should account for existing mixed-shape files already in repo.

# Verification Expectations

1. One canonical filename pattern is documented and enforced.
2. New planning objects are created with canonical filenames.
3. Existing mixed-format planning files are reconciled safely.
4. Planning lookups and references still resolve after migration.
5. Tests cover filename generation and migrated-object lookup behavior.

# Notes
## Migration Note

Filename/numbering reconciliation must update references as part of the same repair.

Reference update scope should include at minimum:
- planning frontmatter refs such as `request_refs`, `spec_ref`, `plan_ref`, `task_refs`, `parent_task_ref`, `standard_refs`
- index / lookup artifacts produced by planning indexing
- docs or generated artifacts that link to planning file paths directly
- any MCP/API lookup behavior that assumes current filename shape

Migration is not complete if canonical filenames exist but inbound/outbound references still point at legacy paths or stale file names.

## Cleanup Requirement

Reconciliation should include cleanup and rebuild of planning-derived state after rename/ref repair.

Cleanup scope should include at minimum:
- planning indexes and lookup artifacts
- planning cache / derived metadata that may preserve old file paths or stale IDs
- orphan/reconcile outputs if they become stale after migration
- any generated dispatch/readiness/trace artifacts that depend on filename shape

Migration should end with a clean regenerate/reindex/validate pass so planning MCP/API reads from canonical state only.

## API Surface Requirement

Planning API / MCP should expose an explicit clean/rebuild indexes maintenance action.

Preferred shape:
- planning API method for cleaning and rebuilding derived planning state
- MCP/admin surface such as `tm_admin op=clean_indexes` or equivalent canonical maintenance verb

The action should cover:
- removing or regenerating stale index artifacts
- rebuilding lookup/readiness/dispatch/trace artifacts from canonical planning docs
- refreshing cache/derived metadata that may contain stale paths
- producing a validation-friendly final state after migration or repair work

Goal: agents and operators should not need to perform manual file-system cleanup to restore planning consistency.

## Consolidation Requirement

Planning repair and rebuild behavior should live behind one canonical maintenance entry point.

Meaning:
- filename reconciliation
- reference repair
- index rebuild
- extract/cache cleanup
- validation / verification after repair

should be orchestrated from one planning API location and one MCP/admin surface, rather than split across multiple ad hoc paths.

Preferred outcome:
- one canonical planning API maintenance method
- one corresponding MCP/admin operation
- other flows delegate to that implementation instead of duplicating cleanup logic

## Naming Convention Requirement

Canonical planning filename conventions should be explicitly defined in config, not only implied by scattered code paths.

That config should clearly capture, per planning kind where needed:
- numeric formatting policy (for example fixed-width zero padding)
- whether filenames always include slug text
- canonical filename pattern shape
- any narrow legacy exceptions, if they must exist

Implementation should read the naming convention from config so create/reconcile/repair flows all apply the same rule.
