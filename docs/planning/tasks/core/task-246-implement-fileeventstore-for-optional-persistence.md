---
id: task-246
label: Implement FileEventStore for optional persistence
state: done
summary: Create FileEventStore with atomic writes, JSON file format, and best-effort
  persistence
spec_ref: spec-23
request_refs:
- request-17
standard_refs:
- standard-5
- standard-6
---












# Description

Implement optional file-backed event persistence. This task owns storing canonical event envelopes durably with atomic writes, using configured runtime location and file naming rules, keeping persistence failures non-fatal to publish.

**File format:**
```
runtime/interoperability/events/
  2026-04-14T12-34-56-123Z_planning.item.state.changed_evt_abc123.json
```

**Key behaviors:**
- Atomic writes: temp file + rename to prevent corruption
- Best-effort: persistence failures logged but don't block publish
- Configurable: enable/disable via `.audiagentic/interoperability/config.yaml`
- Envelope stored: full canonical envelope from task-0248
- Filename format: `{timestamp_utc}_{sanitized_type}_{event_id}.json`
- Query support: filter by timestamp range and event type pattern
- Cleanup: remove old events based on retention_days config

# Acceptance Criteria

- `FileEventStore` persists events to configured runtime location
- Filenames follow: `{timestamp_utc}_{sanitized_type}_{event_id}.json`
- Atomic writes use temp file + rename pattern
- Persistence can be enabled/disabled via config
- Persistence failures logged but don't fail `publish()` call
- Persisted files contain full canonical envelope
- Unit tests cover: successful persistence, disabled mode, write-failure handling
- Smoke test proves FileEventStore imports and basic write path works

# Notes

Replay logic is task-0250. This task is persistence only.
