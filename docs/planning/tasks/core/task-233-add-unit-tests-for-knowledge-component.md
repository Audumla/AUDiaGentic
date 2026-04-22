---
id: task-233
label: Add unit tests for knowledge component
state: draft
summary: Add unit tests for events.py, sync.py, validation.py with 70%+ coverage target
spec_ref: spec-20
parent_task_ref: wp-14
request_refs:
- request-15
standard_refs:
- standard-5
- standard-6
---










# Description
Add focused unit and integration tests for knowledge component core modules. Cover event scanning and state persistence in `events.py`, drift detection and proposal lifecycle in `sync.py`, validation rules in `validation.py`, and search scoring/filtering in `search.py`. Target the gaps that still matter after existing integration fixes: deterministic event handling, proposal cleanup, lifecycle expiry, and search behavior.

# Acceptance Criteria
1. Unit tests cover event state load/save/prune, adapter loading, and scan normalization paths.
2. Unit tests cover sync drift detection, proposal generation, dedupe, cleanup, and status transitions.
3. Unit tests cover validation rules for page compliance and required metadata.
4. Unit tests cover lexical search scoring, filtering, and fuzzy fallback behavior.
5. Coverage for the core knowledge modules reaches at least 70 percent or the repo-defined target.
6. Tests run in CI without relying on live network or external services.

# Notes
- Existing higher-level integration tests should remain green after any unit test additions.
- Prefer small deterministic fixtures over large end-to-end vault fixtures where possible.
