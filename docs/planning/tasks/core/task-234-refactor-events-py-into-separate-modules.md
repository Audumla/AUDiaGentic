---
id: task-234
label: Refactor events.py into separate modules
state: draft
summary: Split events.py (413 lines) into scanning.py, normalization.py, dispatch.py,
  state.py
spec_ref: spec-20
parent_task_ref: wp-14
request_refs:
- request-15
standard_refs:
- standard-5
- standard-6
---










# Description
Refactor the monolithic `events.py` facade into clear internal modules with one responsibility each while preserving the public import surface. The split should reflect the current implementation reality: scanning, normalization, dispatch/handlers, and state I/O already exist as separate concerns and need to be organized so the codebase stays maintainable.

# Acceptance Criteria
1. Event scanning, normalization, dispatch, and state persistence live in separate modules.
2. The public `events.py` module remains a compatibility shim that re-exports the supported API.
3. Each split module has a narrow responsibility and stays under the agreed size target.
4. Existing event processing behavior remains unchanged.
5. Tests still pass for event ingestion, state changes, and proposal generation.

# Notes
- Align module names with the current internal split already in place where possible.
- Avoid changing event semantics during the refactor; this is structure work, not behavior work.
