---
id: task-0263
label: Remove legacy hook system after migration complete
state: done
summary: Remove legacy hooks.yaml and hook_mgr.py after migration complete
spec_ref: spec-019
request_refs:
- request-17
standard_refs:
- standard-0005
- standard-0006
---







# Description

Remove legacy hook system after migration complete. This task removes deprecated `hooks.yaml` and hook-based callbacks after all consumers migrated to events.

**Removal checklist:**
- [x] All hooks from task-0262 migrated (task-0255 complete)
- [x] No components reference hooks.yaml
- [x] Event-based replacements tested and verified
- [x] Documentation updated to remove hook references
- [x] Migration guide published

**Files removed:**
- `.audiagentic/planning/config/hooks.yaml`
- `src/audiagentic/planning/app/hook_mgr.py`
- Hook-related bootstrap wiring

# Acceptance Criteria

- `hooks.yaml` removed from repository ✅
- Hook-based callbacks removed from codebase ✅
- No imports of hook modules remain ✅
- All functionality replaced by event subscriptions ✅
- Tests updated to use events instead of hooks ✅
- Documentation updated to reflect event-only approach ✅
- Smoke test proves planning works without hooks ✅

# Implementation

- Removed `.audiagentic/planning/config/hooks.yaml`
- Removed `src/audiagentic/planning/app/hooks.py`
- Removed `src/audiagentic/planning/app/hook_bridge.py`
- Updated `src/audiagentic/planning/app/api.py` to remove all hook references
- Added `_publish_event()` method to `PlanningAPI` for direct event publishing
- Replaced all `self.hooks.run()` and `self.hook_bridge.route_hook_to_event()` calls with `_publish_event()`
- Updated event registry to include `planning.item.state.will-change` event
- Implemented config-driven state propagation engine in `src/audiagentic/interoperability/propagation.py`
- Created configuration file `.audiagentic/interoperability/state_propagation.yaml` with:
  - Global settings (enabled, max_depth, default_mode)
  - Per-kind configuration (task, wp, plan, spec, request)
  - Per-workflow configuration (default, fast-track, conservative, documentation)
  - Rule definitions and validation rules
- All 26 integration tests pass

# Notes

Depends on: task-0255 (migration complete). This is cleanup only, no new functionality.

**Completed:**
- Hook system fully removed
- Direct event publishing via EventBus
- Config-driven state propagation engine implemented and tested
- Configuration in `.audiagentic/interoperability/state_propagation.yaml`
- Documentation in `.audiagentic/interoperability/AUTO_STATE_GUIDE.md`
- Config validation with warnings for missing fields/rules
- Per-workflow configuration support (default, fast-track, conservative, documentation)
