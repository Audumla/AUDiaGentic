---
id: plan-013
label: Interoperability layer and state propagation implementation plan
state: in_progress
summary: Implement event-driven interoperability layer and automatic state propagation
  for planning hierarchies
spec_refs:
- spec-019
- spec-020
request_refs:
- request-17
- request-18
work_package_refs:
- ref: wp-0023
standard_refs:
- standard-0006
---









# Objectives

1. Implement lightweight interoperability event layer (request-17, spec-019)
   - EventBus with explicit dependency injection (singleton for bootstrap)
   - Optional file persistence with crash recovery (V2)
   - Replay with opt-in dispatch (default: skip replayed events)
   - Single and multi-segment wildcards (* and **)
   - Threading-based async queue (not asyncio)
2. Enable automatic state propagation across planning hierarchies (request-18, spec-020)
3. Bridge legacy hooks to canonical events (task-0255, task-0262, task-0263)
4. Provide CLI diagnostics and repair tools (task-0259, task-0265)
5. Integrate with knowledge component for cross-component workflows (task-0254, task-0261)

# Delivery Approach

## Phase 1: Foundation (Week 1)
- task-0257: Package scaffolding and bootstrap wiring
- task-0248: EventBus core (SYNC/ASYNC, cycle detection)
- task-0249: FileEventStore (atomic writes, best-effort persistence)
- task-0250: Replay service (is_replay flag, filtering)
- task-0264: AsyncQueue (background worker, graceful shutdown)

## Phase 2: Planning Integration (Week 2)
- task-0252: State propagation config system
- task-0251: State propagation engine (rules, conflict resolution)
- task-0253: Planning component integration (emit events)
- task-0258: Event schema registry and documentation

## Phase 3: Cross-Component (Week 3)
- task-0254: Knowledge component integration (subscribe to events)
- task-0261: Knowledge event handler (sync actions on state changes)
- task-0255: Hook migration (bridge legacy hooks to events)
- task-0262: Hook inventory and migration plan
- task-0263: Remove legacy hooks (cleanup)

## Phase 4: Tooling & Validation (Week 4)
- task-0259: CLI commands (list, replay, debug, cleanup, audit)
- task-0265: Planning audit and repair CLI
- task-0260: Performance validation and benchmarking
- task-0256: Integration tests (end-to-end scenarios)

## Phase 5: Rollout (Week 5)
- Enable propagation by default
- Monitor propagation logs
- Run audit tool on existing hierarchies
- Document migration guide

# Dependencies

## Internal Dependencies
- spec-019 must be `ready` before implementation starts ✅
- spec-020 must be `ready` before implementation starts ✅
- request-17 must be `distilled` ✅
- request-18 must be `distilled` ✅

## External Dependencies
- Knowledge component integration (task-0254, task-0261)
- Planning component state API (task-0253)
- Existing hook system (task-0255, task-0262)

## Task Dependencies

```
task-0257 (scaffolding)
  -> task-0248 (EventBus)
  -> task-0249 (FileEventStore)
  -> task-0250 (Replay)
  -> task-0264 (AsyncQueue)
  
task-0248 + task-0252
  -> task-0251 (propagation engine)
  -> task-0253 (planning integration)
  
task-0251 + task-0253
  -> task-0254 (knowledge integration)
  -> task-0261 (knowledge handler)
  
task-0262
  -> task-0255 (hook migration)
  -> task-0263 (hook removal)
  
task-0248 through task-0264
  -> task-0259 (CLI commands)
  -> task-0265 (audit CLI)
  -> task-0260 (performance validation)
  -> task-0256 (integration tests)
```

# Work Packages

## WP-0023: Event Layer Core
- task-0248: EventBus core
- task-0249: FileEventStore
- task-0250: Replay service
- task-0264: AsyncQueue
- task-0257: Package scaffolding

## WP-0024: State Propagation
- task-0251: Propagation engine
- task-0252: Config system
- task-0253: Planning integration
- task-0258: Event schema registry

## WP-0025: Cross-Component Integration
- task-0254: Knowledge integration
- task-0261: Knowledge event handler
- task-0255: Hook migration
- task-0262: Hook inventory
- task-0263: Hook removal

## WP-0026: Tooling & Validation
- task-0259: CLI commands
- task-0265: Audit CLI
- task-0260: Performance validation
- task-0256: Integration tests

# Risk Assessment

## High Risk
- **Async queue reliability**: Events must not be lost during normal operation
  - Mitigation: Persist queue to disk on checkpoint (V2), graceful shutdown with drain
- **Async queue crash loss**: V1 events in queue are silently lost on crash
  - Mitigation: Document in config, set `persist_on_checkpoint: true` in V2
- **Hook migration breaking existing workflows**: Must preserve backward compatibility
  - Mitigation: Keep hooks as compatibility bridge, test both paths

## Medium Risk
- **Performance targets missed**: <50ms latency, 100 events/sec throughput
  - Mitigation: Benchmark early (task-0260), optimize if needed
- **Propagation loops**: Cycle detection must prevent infinite loops
  - Mitigation: propagation_depth limit (10), correlation_id tracking

## Low Risk
- **Knowledge integration**: Read-only subscription, minimal coupling
- **CLI commands**: Independent of core logic, easy to test

# Acceptance Criteria

## AC-1: Event Layer Complete
- [ ] EventBus publishes/subscribes with SYNC/ASYNC modes
- [ ] EventBus supports explicit dependency injection (singleton for bootstrap)
- [ ] FileEventStore persists events with atomic writes
- [ ] Replay service re-publishes events with is_replay flag (opt-in dispatch default)
- [ ] AsyncQueue processes events in background (threading-based)
- [ ] Wildcards: single-segment (*) and multi-segment (**)
- [ ] Performance targets met with failure semantics (<50ms SYNC, <5ms ASYNC, ≥100/sec)
- [ ] All 18 tasks from request-17 complete

## AC-2: State Propagation Complete
- [ ] Task→WP, WP→Plan, Plan→Spec propagation works
- [ ] Configurable rules via state_propagation.yaml
- [ ] Conflict resolution (blocked > in_progress > ready)
- [ ] Rollback handling (task done→ready reverts WP)
- [ ] All tasks from request-18 complete

## AC-3: Integration Complete
- [ ] Planning emits events after state commits
- [ ] Knowledge subscribes to planning events
- [ ] Cross-component trigger works (task done → knowledge sync)
- [ ] Legacy hooks migrated to events (task-0255)
- [ ] Legacy hooks removed (task-0263)

## AC-4: Tooling Complete
- [ ] CLI commands: events list, replay, debug, cleanup
- [ ] CLI command: planning audit --fix
- [ ] Performance targets met (<50ms, 100 events/sec)
- [ ] Integration tests pass (task-0256)

## AC-5: Documentation Complete
- [ ] API documentation for EventBus, propagation engine
- [ ] Event taxonomy documented (planning, knowledge, interop)
- [ ] Config file schema documented (including async crash recovery note)
- [ ] Migration guide from manual to automatic state management
- [ ] Troubleshooting guide for propagation issues
- [ ] Async queue crash recovery documented (V1 vs V2)
- [ ] Replay opt-in behavior documented
- [ ] Wildcard patterns (* and **) documented with examples

# Rollout Plan

## Stage 1: Development (Weeks 1-4)
- Implement all tasks
- Run unit tests
- Benchmark performance

## Stage 2: Beta (Week 5)
- Enable for internal team
- Monitor propagation logs
- Collect feedback

## Stage 3: Production (Week 6)
- Enable for all users
- Run audit tool on existing hierarchies
- Document migration guide

## Stage 4: Cleanup (Week 7)
- Remove legacy hooks (task-0263)
- Update documentation
- Archive old hook-based workflows

# Notes
Assessment on 2026-04-17: plan remains active but reduced in scope. Core propagation landed; remaining work is concentrated in knowledge-side handler correctness and audit/repair tooling.

Remaining plan scope explicitly includes `task-0006` after observing invalid automatic parent transitions during planning-MCP state changes on 2026-04-17.
