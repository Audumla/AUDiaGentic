---
id: task-0261
label: Implement knowledge event handler for planning state changes
state: done
summary: Implement knowledge event handler for planning state changes with runtime
  adapter/handler execution and replay-safe filtering
spec_ref: spec-019
request_refs:
- request-17
standard_refs:
- standard-0005
- standard-0006
---











# Description

Implement knowledge event handler for planning state changes. This task owns filtering events by `subject.kind` and `payload.new_state`, then triggering appropriate knowledge sync actions.

**Handler logic:**
```python
def knowledge_event_handler(event_type, payload, metadata):
    if metadata.get("is_replay"):
        return  # Skip replayed events
    
    kind = payload.get("subject", {}).get("kind")
    new_state = payload.get("new_state")
    
    if kind == "task" and new_state in ("done", "verified"):
        mark_related_pages_stale(kind, payload.get("subject", {}).get("id"))
    elif kind == "wp" and new_state == "done":
        generate_sync_proposal_for_plan(kind, payload)
    # ... etc
```

**Actions:**
- `task` done/verified → mark related work-package/implementation pages stale
- `wp` done → generate sync proposal for plan/current-state pages
- `plan` done → review spec/overview pages
- `blocked` → mark operational pages stale (don't rewrite)
- Skip `is_replay: true` events
- Optional opt-in via config: `config.replay.dispatch_on_replay: true`

# Acceptance Criteria

- Handler filters by `subject.kind` (task, wp, plan, spec)
- Handler filters by `payload.new_state` (done, verified, in_progress, blocked)
- **Opt-in replay:** Handler skips replayed events unless `config.replay.dispatch_on_replay: true`
- Appropriate knowledge actions triggered per event type/state
- Unit tests cover: filtering, replay skip, action triggering, opt-in behavior
- Integration test covers: planning state change → knowledge action
- Smoke test proves handler executes without errors

# Notes
Depends on: task-0254 (knowledge subscription). Uses existing knowledge sync/stale marking APIs.

Implemented on 2026-04-17: fixed runtime planning-event handling in `src/audiagentic/knowledge/events.py` so it reads `subject` from event metadata, honors replay opt-in from `.audiagentic/interoperability/config.yaml`, resolves affected pages from knowledge adapter config, and executes configured knowledge actions without calling stale-marking APIs with the wrong signature. Added integration coverage in `tests/integration/test_knowledge_event_handler.py` for done, blocked, replay-skip, and replay-opt-in scenarios. Verified with `pytest tests/integration/test_knowledge_event_handler.py -q` -> 4 passed.
