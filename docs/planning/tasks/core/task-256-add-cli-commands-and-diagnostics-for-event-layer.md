---
id: task-256
label: Add CLI commands and diagnostics for event layer
state: cancelled
summary: 'Implement CLI commands for event layer diagnostics — blocked: deferred until
  core is stable and operational need confirmed in practice'
spec_ref: spec-23
request_refs:
- request-17
standard_refs:
- standard-5
- standard-6
---
















# Description

Implement CLI commands for event layer diagnostics and management. This task adds CLI surface for event inspection, replay, and cleanup.

**Commands:**
```bash
audiagentic events list [--from TIMESTAMP] [--to TIMESTAMP] [--type PATTERN]
  # List persisted events
  
audiagentic events replay [--from TIMESTAMP] [--to TIMESTAMP] [--type PATTERN]
  # Replay events
  
audiagentic events debug EVENT_ID
  # Show event details
  
audiagentic events cleanup [--older-than DAYS]
  # Remove old event files
```

**Note:** Deferred until core is stable and operational need confirmed.

# Acceptance Criteria

- `events list` shows persisted events with filtering
- `events replay` triggers replay with filtering
- `events debug` shows full event envelope for given ID
- `events cleanup` removes old event files safely
- CLI commands integrated into existing audiagentic CLI
- Unit tests cover: command parsing, filtering, cleanup safety
- Smoke test proves CLI commands execute without errors

# Notes
Deferred until core is stable and operational need confirmed. Depends on: task-249 (persistence), task-0250 (replay).

Cancelled on 2026-04-17 during request assessment. Diagnostic event CLI work was explicitly deferred in the task notes and is no longer required to treat core propagation behavior as the active remaining scope.
