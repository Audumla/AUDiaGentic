## Summary
The **Event Bridge Pattern** defines how to connect external event sources (planning, runtime, file changes) to the knowledge component's sync system. It provides a standardized approach for watching events, filtering them, and triggering knowledge updates through configurable adapters.

## Current state
**Pattern Structure:**

```
Event Source → Event Stream → Adapter → Filter → Transform → Action → Knowledge Update
```

**Components:**

1. **Event Source**: System that emits events
   - Planning system: `.audiagentic/planning/events/events.jsonl`
   - Runtime: Custom NDJSON logs
   - File system: File change monitoring

2. **Event Stream**: Format for events
   - NDJSON (one JSON object per line)
   - Fields: `ts`, `event`, `id`, payload fields
   - Example: `{"ts": "...", "event": "task.after_state_change", "id": "task-0258", "new_state": "done"}`

3. **Adapter**: Configuration bridging source to knowledge
   - Defined in `docs/knowledge/events/adapters.yml`
   - Specifies source kind, paths, filters, actions

4. **Filter**: Select relevant events
   - `event_name_patterns`: Glob patterns
   - `payload_filters`: Field value matching
   - `equals`, `in`, `contains_any`

5. **Transform**: Normalize event format
   - Map source fields to knowledge event schema
   - Add metadata (source_system, occurred_at)

6. **Action**: What to do with matched events
   - `generate_sync_proposal`
   - `mark_stale`
   - `mark_stale_and_generate_sync_proposal`
   - `ignore`

**Example Implementation:**
```yaml
adapters:
  - id: planning-task-completed-bridge
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
    affects_pages:
      - system-planning
    action: mark_stale_and_generate_sync_proposal
```

**Processing Flow:**
1. `scan-events`: Read event sources, apply filters
2. `process-events`: Generate proposals, mark pages stale
3. Review proposals in `docs/knowledge/proposals/`
4. Apply updates to knowledge pages

## How to use
**Implementing an Event Bridge:**

1. **Identify Event Source**:
   - What system emits events?
   - What format are events in?
   - Where are events stored?

2. **Create Adapter Configuration**:
   ```yaml
   - id: <unique-id>
     source_kind: event_stream | file_change
     path_globs:
       - <path-to-events>
     event_name_patterns:
       - <event-patterns>
     payload_filters:
       <filter-config>
     affects_pages:
       - <page-ids>
     action: <action-type>
   ```

3. **Test the Adapter**:
   ```bash
   # Scan for events
   audiagentic-knowledge --root . scan-events
   
   # Process events
   audiagentic-knowledge --root . process-events
   
   # Check proposals
   ls -la docs/knowledge/proposals/
   ```

4. **Monitor and Maintain**:
   - Check event processing regularly
   - Review and apply proposals
   - Update adapter as event schema changes

**Common Patterns:**

**Planning Events Bridge:**
```yaml
- id: planning-bridge
  source_kind: event_stream
  path_globs:
    - .audiagentic/planning/events/events.jsonl
  event_name_patterns:
    - task.after_state_change
  payload_filters:
    in:
      new_state:
        - done
  affects_pages:
    - system-planning
  action: mark_stale_and_generate_sync_proposal
```

**Config Change Bridge:**
```yaml
- id: config-change-bridge
  source_kind: file_change
  path_globs:
    - .audiagentic/**/*.yml
  affects_pages:
    - system-knowledge
  action: generate_sync_proposal
```

**Best Practices:**
- Use specific event filters to avoid noise
- List all affected pages explicitly
- Start with `action: ignore` to test
- Gradually enable actions after validation
- Document event schema in affected pages

## Sync notes
This page documents the event bridge pattern. It should be refreshed when:
- New source kinds are added
- Filter options change
- Action types are modified
- Adapter schema is updated

**Sources:**
- `src/audiagentic/knowledge/events.py` - Event processing
- `docs/knowledge/events/adapters.yml` - Current adapters
- Event adapter schema

**Sync frequency:** On event system changes

## References
- [Knowledge System](../systems/system-knowledge.md)
- [Glossary: Event Adapter](../glossary/glossary-event-adapter.md)
- [Decision: Event-Driven Sync](../decisions/decision-event-driven-sync.md)
- Event adapters: `docs/knowledge/events/adapters.yml`
