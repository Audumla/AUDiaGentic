---
id: task-0332
label: Refactor managers to use config
state: done
summary: Refactor SpecMgr, TaskMgr, PlanMgr, WPMgr, StandardMgr to use TemplateEngine
spec_ref: spec-0029
request_refs: []
standard_refs:
- standard-0005
- standard-0006
---




# Description

Refactor all planning managers to use TemplateEngine for body generation instead of hardcoded templates.

## Managers to Refactor

1. **SpecMgr** - Replace hardcoded body at line 18
2. **TaskMgr** - Replace hardcoded body at line 34
3. **PlanMgr** - Replace hardcoded body at line 28
4. **WPMgr** - Replace hardcoded body at line 13
5. **StandardMgr** - Replace hardcoded body at line 9

## Required Changes

Each manager must:
1. Import TemplateEngine
2. Initialize TemplateEngine with config
3. Call template_engine.render(kind, guidance) instead of hardcoded string
4. Support optional guidance parameter to override template

## Related Tasks

- task-3251: Refactor section_registry to use config
- task-3252: Clean up req_mgr hardcoded defaults
- task-3253: Integrate relationship validation into managers

# Acceptance Criteria

1. No hardcoded body templates in spec_mgr, task_mgr, plan_mgr, wp_mgr, std_mgr
2. All managers use TemplateEngine.render() for body generation
3. Managers support optional guidance parameter
4. Existing documents remain valid
5. All existing tests pass

# Notes
