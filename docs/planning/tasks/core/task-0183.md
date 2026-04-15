---
id: task-0183
label: Verify and preserve schema-compliant task reference placement
state: done
summary: Confirm the real schema layout for task and work-package task references
  and remove the stale meta.task_refs assumption from the implementation slice
spec_ref: spec-002
---


# Description

The original hardening notes assumed task creation was writing `task_refs` at the top level and that the schema required `meta.task_refs`. That is not how the current planning model works:

- tasks do not currently carry top-level `task_refs`
- work packages legitimately carry top-level `task_refs`
- specifications also legitimately carry top-level `task_refs`

This task is to verify the actual schema contract, keep the correct top-level relation fields where the schema requires them, and remove the stale `meta.task_refs` assumption from the planning slice so implementation can focus on the real bugs.

# Acceptance Criteria

1. Task, specification, and work-package schema placement is verified against the live schemas
2. No runtime change is made that would move valid top-level `task_refs` into `meta`
3. Planning docs in this implementation slice no longer instruct implementers to use `meta.task_refs`
4. `tm_validate()` passes after the planning cleanup
5. No breaking changes are introduced to existing relationship handling

# Notes

- This is primarily a planning correction task, not a data migration task
- The real runtime work in this slice is delete handling, counter safety, request traceability, duplicate detection, validation feedback, and integration coverage
- Implementation result: verified that the live schemas already use the correct relation layout. Tasks do not carry `task_refs`, while specifications and work packages legitimately keep top-level `task_refs`. The planning slice was updated to remove the stale `meta.task_refs` assumption, and validation remains clean.
