---
id: task-11
label: Implement lifecycle tracking for proposals and jobs
state: done
summary: Add lifecycle.py with Job/Proposal status tracking, history, and rollback
  capability
domain: core
spec_ref: wp-13
standard_refs:
- standard-5
- standard-6
---




# Description\n\nImplement lifecycle tracking for long-running knowledge operations (proposals, jobs).\n\n1. **lifecycle.py** module with:\n   - Job class: id, status, created_at, updated_at, history\n   - Proposal class: id, kind, payload, status (pending/approved/rejected/applied), history\n   - Status transitions with validation\n   - History tracking (who, when, what changed)\n   - Rollback capability for failed jobs\n\n2. **Integration**:\n   - Hook into bootstrap/sync operations\n   - Track proposal lifecycle (created → approved → applied)\n   - Track job lifecycle (queued → running → completed/failed)\n\n3. **Persistence**:\n   - Store in .audiagentic/knowledge/runtime_data/lifecycle.jsonl (event log style)\n   - Load on startup for resume capability\n\n# Acceptance Criteria\n\n- [ ] lifecycle.py created with Job/Proposal classes\n- [ ] Status transitions validated (e.g., can't go from completed → running)\n- [ ] History tracking works (each change recorded with timestamp, actor)\n- [ ] Rollback logic implemented for failed jobs\n- [ ] Tests demonstrate lifecycle state machine\n- [ ] Persistence layer works (write/read lifecycle events)\n- [ ] CLI or API to query job/proposal status\n\n# Notes\n\nStart simple: in-memory state machine + simple file persistence.\nExtend later with database if needed.\nConsider audit trail use case (who approved what, when).\n"
