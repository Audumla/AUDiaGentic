---
id: task-0232
label: Bootstrap knowledge component configuration
state: done
summary: Bootstrap the knowledge component configuration files and registries using
  the bootstrap module.
spec_ref: spec-014
request_refs: []
standard_refs:
- standard-0005
- standard-0006
---







# Description


# Acceptance Criteria


# Notes

### Critical Review Findings (2026-04-14)

**Issues Found and Fixed:**

1. **Event adapter configuration was incorrect**:
   - Used `source_kind: file_change` instead of `source_kind: event_stream`
   - Used wrong field names (`watch_paths` instead of `path_globs`)
   - Had non-existent `transform` section
   - Fixed to match the expected schema from sample_vault

2. **Actions registry had wrong module names**:
   - Referenced `audiagentic_knowledge.events` instead of `audiagentic.knowledge.events`
   - Referenced `audiagentic_knowledge.actions` instead of `audiagentic.knowledge.actions`
   - Fixed all handler references in `knowledge/registries/actions.yml`

3. **No knowledge pages exist**:
   - `affects_pages` field is empty (correctly set to `[]`)
   - Action set to `ignore` until current-state pages are created
   - This is expected - knowledge vault is newly bootstrapped

4. **Event format mapping**:
   - Planning events use: `{"ts": "...", "event": "task.after_state_change", "id": "...", "new_state": "done"}`
   - Knowledge adapter expects: `event_name` or `type` field, but planning uses `event` field
   - Adapter handles this via fallback: `event_name: planning.task.completed` in config
   - Event filtering works correctly: 2132 events processed from events.jsonl

**Verification:**
- `record-event-baseline`: Successfully recorded 2132 events from planning events file
- `scan-events`: Working correctly
- `process-events`: Working correctly (action set to `ignore` until pages exist)
- `doctor`: No issues found

**Files Modified:**
- `knowledge/registries/actions.yml`: Fixed module names from `audiagentic_knowledge.*` to `audiagentic.knowledge.*`
- `knowledge/events/adapters.yml`: Corrected adapter schema to use `source_kind: event_stream` with proper fields
