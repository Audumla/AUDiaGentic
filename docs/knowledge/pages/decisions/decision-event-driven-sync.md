---
id: decision-event-driven-sync
title: Event-Driven Sync Architecture
type: decision
status: current
summary: Decision to use event-driven architecture for knowledge updates, where external events automatically trigger knowledge sync proposals
owners:
- core-team
updated_at: '2026-04-15'
tags:
- decision
- architecture
- events
- sync
related:
- system-knowledge
- pattern-event-bridge
---

## Summary
Decision to use event-driven architecture for knowledge updates, where external events (planning task completions, runtime changes) automatically trigger knowledge sync proposals. This keeps documentation synchronized with system state without manual intervention.

## Current state
**Decision Date:** 2026-04-14 (knowledge component integration)

**Status:** Implemented

**Context:**
Knowledge documentation can become stale when the system it documents changes. Manual updates are error-prone and often delayed. The knowledge component needed a mechanism to detect changes and propose updates automatically.

**Decision:**
Use event-driven sync where:
1. External systems emit events (planning, runtime, file changes)
2. Event adapters watch for relevant events
3. Matching events generate sync proposals
4. Humans review and apply proposals
5. Knowledge stays synchronized with minimal manual effort

**Rationale:**
- **Automation**: Reduces manual sync effort
- **Timeliness**: Updates proposed immediately after changes
- **Audit trail**: Events logged, proposals tracked
- **Safety**: Human review before applying changes
- **Flexibility**: Adapters configurable per source

**Implementation:**
- Event adapters in `docs/knowledge/events/adapters.yml`
- Planning events bridge: `.audiagentic/planning/events/events.jsonl`
- Event processing: `scan-events` → `process-events`
- Proposals generated in `docs/knowledge/proposals/`
- 2132+ planning events processed at integration

**Architecture:**
```
External System → Events → Adapter → Filter → Action → Proposal → Review → Update
     (planning)   (JSONL)  (YAML)   (config) (sync)   (YAML)   (human)  (page)
```

**Consequences:**
- ✅ Knowledge stays fresher with less effort
- ✅ Clear audit trail of changes
- ✅ Human oversight maintained
- ⚠️ Requires event infrastructure
- ⚠️ Adapters need maintenance
- ⚠️ Proposal review is still manual work

**Alternatives Considered:**
1. **Manual sync**: Simple but error-prone and delayed
2. **Scheduled sync**: Periodic scans, but not immediate
3. **Auto-apply changes**: Faster but risky without review
4. **File watchers only**: Misses logical events (task completion)

## How to use
**Configure Event Adapters:**

1. Add adapter to `docs/knowledge/events/adapters.yml`
2. Specify source (file or event stream)
3. Configure filters (event names, payload values)
4. Set action (generate proposal, mark stale, etc.)
5. List affected pages

**Process Events:**
```bash
# Scan for new events
audiagentic-knowledge --root . scan-events

# Process and generate proposals
audiagentic-knowledge --root . process-events

# Review proposals in docs/knowledge/proposals/
```

**Current Adapters:**
- `planning-task-completed-bridge`: Watches for task completions
- Configurable to watch other event sources

## Sync notes
This is an architecture decision record (ADR). It should be updated if:
- The event-driven approach is changed
- New event sources are added
- Processing pipeline is modified

**Sources:**
- `src/audiagentic/knowledge/events.py` - Event processing
- `docs/knowledge/events/adapters.yml` - Current adapters
- Event processing actions

**Sync frequency:** If event architecture changes

## References
- [Knowledge System](../systems/system-knowledge.md)
- [Glossary: Event Adapter](../glossary/glossary-event-adapter.md)
- [Pattern: Event Bridge](../patterns/pattern-event-bridge.md)
- Event adapters: `docs/knowledge/events/adapters.yml`
