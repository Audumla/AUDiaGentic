---
id: task-236
label: Add lifecycle management for jobs and proposals
state: draft
summary: Add expiry, cleanup, status tracking for LLM jobs and sync proposals
spec_ref: spec-20
parent_task_ref: wp-14
request_refs:
- request-15
standard_refs:
- standard-5
- standard-6
---










# Description
Add lifecycle management so knowledge jobs and sync proposals do not accumulate forever. This should cover timestamps, expiry/retention, safe cleanup, status transitions, and recovery from partially written or stale records.

# Acceptance Criteria
1. Jobs track creation, update, and expiry timestamps.
2. Stale jobs are cleaned up safely without corrupting active state.
3. Sync proposals track status transitions such as pending, accepted, rejected, and merged.
4. Proposal cleanup removes or archives stale records according to retention policy.
5. Job and proposal writes remain atomic and recoverable on load.
6. Tests verify expiry, cleanup, and recovery behavior.

# Notes
- Keep deterministic behavior first; lifecycle should not introduce hidden background side effects.
- Use config-driven retention values so operators can tune cleanup without code changes.
