---
id: glossary-event-adapter
title: Event Adapter
type: glossary_term
status: current
summary: Configuration object bridging external events to knowledge component sync system, defining how to watch, filter, transform events and trigger actions
owners:
- core-team
updated_at: '2026-04-15'
tags:
- glossary
- events
- configuration
related:
- system-knowledge
- pattern-event-bridge
---

## Summary
An **event adapter** is a configuration object that bridges external events (from planning, runtime, or other sources) to the knowledge component's sync system. Adapters define how to watch for events, filter them, transform them, and what actions to take when events occur. They are the primary mechanism for event-driven knowledge updates.

## Current state
**Adapter Configuration** (`docs/knowledge/events/adapters.yml`):

```yaml
adapters:
  - id: planning-task-completed-bridge
    name: Planning Task Completion Bridge
    source_kind: event_stream
    path_globs:
      - .audiagentic/planning/events/events.jsonl
    event_name_patterns:
      - task.after_state_change
    payload_filters:
      in:
        new_state:
          - done
    status_field: new_state
    summary_fields:
      - id
      - new_state
    event_name: planning.task.completed
    affects_pages: []
    action: ignore
```

**Source Kinds:**

| Kind | Description | Example |
|------|-------------|---------|
| `file_change` | Watch files for content changes | Config files, source code |
| `event_stream` | Process NDJSON event logs | Planning events, runtime logs |

**Actions:**

| Action | Description |
|--------|-------------|
| `generate_sync_proposal` | Create proposal in `proposals/` |
| `mark_stale` | Mark affected pages as stale |
| `mark_stale_and_generate_sync_proposal` | Both of above |
| `ignore` | Log event but take no action |

**Filtering:**
- `event_name_patterns`: Glob patterns for event names
- `payload_filters`: Filter by payload field values
  - `equals`: Exact match
  - `in`: Value in list
  - `contains_any`: String contains any token

**Current Adapters:**
- `planning-task-completed-bridge`: Bridges planning task completion events
  - Source: `.audiagentic/planning/events/events.jsonl`
  - Filters: `task.after_state_change` where `new_state=done`
  - Action: `ignore` (until knowledge pages reference planning state)

## How to use
**Creating an Event Adapter:**

1. **Define adapter in YAML**: Add to `docs/knowledge/events/adapters.yml`
2. **Specify source**: `path_globs` for files to watch
3. **Configure filtering**: `event_name_patterns` and `payload_filters`
4. **Set action**: What to do when events match
5. **List affected pages**: `affects_pages` for sync targeting

**Example: Watch Config Changes:**
```yaml
- id: config-change-adapter
  source_kind: file_change
  path_globs:
    - .audiagentic/**/*.yml
    - .audiagentic/**/*.yaml
  event_name: config.changed
  affects_pages:
    - system-knowledge
    - system-planning
  action: mark_stale_and_generate_sync_proposal
```

**Example: Runtime Event Stream:**
```yaml
- id: runtime-events-adapter
  source_kind: event_stream
  path_globs:
    - knowledge/source_material/runtime/**/*.ndjson
  event_name_patterns:
    - runtime.*
  payload_filters:
    equals:
      payload.severity: important
  affects_pages:
    - system-runtime
  action: generate_sync_proposal
```

**Testing Adapters:**
```bash
# Scan for new events
audiagentic-knowledge --root . scan-events

# Process events
audiagentic-knowledge --root . process-events

# Record baseline
audiagentic-knowledge --root . record-event-baseline
```

## Sync notes
This page should be refreshed when:
- New source kinds are added
- Action types change
- Adapter schema is modified
- Filtering options are updated

**Sources:**
- `src/audiagentic/knowledge/events.py` - Event processing
- `docs/knowledge/events/adapters.yml` - Current adapters
- Event adapter schema in bootstrap defaults

**Sync frequency:** On event system changes

## References
- [Knowledge System](../systems/system-knowledge.md)
- [Pattern: Event Bridge](../patterns/pattern-event-bridge.md)
- Event adapters: `docs/knowledge/events/adapters.yml`
