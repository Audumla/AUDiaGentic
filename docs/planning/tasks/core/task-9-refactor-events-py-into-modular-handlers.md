---
id: task-9
label: Refactor events.py into modular handlers
state: done
summary: 'Split 792-line events.py into focused modules: handler dispatch, state machine,
  validation rules'
domain: core
spec_ref: wp-13
standard_refs:
- standard-5
- standard-6
---




# Description\n\nevents.py (792 lines) is monolithic. Refactor into 3 focused modules:\n\n1. **events_handler.py** — Event dispatch, routing to handlers by event type\n2. **events_state.py** — State machine logic for knowledge lifecycle (init, update, delete, archive)\n3. **events_validation.py** — Event validation rules, constraint checking\n\nEach module <300 lines. Keep public API stable (no breaking changes to imports).\n\n# Acceptance Criteria\n\n- [ ] events.py split into 3 modules in src/audiagentic/knowledge/\n- [ ] Each module is <300 lines\n- [ ] Public API unchanged (imports still work from events module)\n- [ ] All event handlers work (test with existing integration tests)\n- [ ] No performance regression\n- [ ] Code is more maintainable (clear separation of concerns)\n\n# Notes\n\nKeep __init__.py or create events/ subpackage to maintain backward compatibility.\nUpdate imports in cli.py, sync.py, actions.py to use new modules if cleaner.\n"
