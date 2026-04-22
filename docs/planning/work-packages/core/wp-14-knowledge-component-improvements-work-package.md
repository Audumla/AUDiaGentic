---
id: wp-14
label: Knowledge Component Improvements Work Package
state: done
summary: Tasks for addressing critical review findings
plan_ref: plan-15
task_refs:
- ref: task-8
  seq: 1000
- ref: task-9
  seq: 2000
- ref: task-10
  seq: 3000
- ref: task-11
  seq: 4000
standard_refs:
- standard-6
---













# Objective

Implement knowledge component improvements identified in critical review: comprehensive test coverage, refactored event handling, enhanced search, and lifecycle tracking.

# Scope of This Package

4 focused tasks:
1. Add unit test coverage for knowledge component modules (search, bootstrap, sync, config)
2. Refactor events.py (792 lines) into modular event handler, state machine, validation
3. Enhance search from token-based weighting to fuzzy matching or BM25
4. Implement lifecycle tracking for proposals and jobs (status, history, rollback)

# Inputs

- Current knowledge component: src/audiagentic/knowledge/ (23 modules, 4.7K LOC)
- Existing test files: 2 integration tests (minimal coverage)
- Events.py: 792 lines, monolithic event handling
- Search.py: 136 lines, token-based with metadata filtering
- Request-15: Critical review findings from 2026-04-14

# Instructions

1. Create tasks in order (tests first, then refactoring, then enhancements)
2. Each task should target a single module or concern
3. Use standard-0006 for test structure and coverage expectations
4. Follow existing code patterns (models, config, validation approach)
5. Update README and docs as you go

# Required Outputs

- 40+ unit tests covering core modules (search, bootstrap, sync, config, models)
- events.py split into: events_handler.py (event dispatch), events_state.py (state machine), events_validation.py (rules)
- search.py enhanced with fuzzy matching (or BM25 if chosen after analysis)
- lifecycle.py implementing Job/Proposal tracking with status, history, rollback
- Updated knowledge/README.md with test and module overview

# Acceptance Checks

- [ ] Unit tests run clean, coverage >80% for search/bootstrap/sync/config
- [ ] events.py split: 3 focused modules, each <300 lines
- [ ] Search tests demonstrate fuzzy matching behavior
- [ ] Lifecycle API tests demonstrate status transitions and history
- [ ] All tests passing
- [ ] No regressions in existing MCP tools or CLI

# Non-Goals

- Rewriting LLM module (llm.py stays as-is unless test-required refactoring)
- Major CLI surface changes
- Breaking changes to MCP tools
