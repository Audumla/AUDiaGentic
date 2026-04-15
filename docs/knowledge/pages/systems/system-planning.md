## Summary
The AUDiaGentic planning system provides structured workflow management for software engineering tasks. It organizes work through a hierarchy of artifacts: requests, specifications, plans, work packages, and tasks. The system uses markdown files with YAML frontmatter stored in `docs/planning/` and maintains an event log for audit trails.

## Current state
The planning system consists of:

**Artifact Types:**
- **Requests** (`docs/planning/requests/`): Captured work items, problems, or opportunities
- **Specifications** (`docs/planning/specifications/`): Detailed technical specifications for solutions
- **Plans** (`docs/planning/plans/`): High-level implementation plans linking specs to work
- **Work Packages** (`docs/planning/work-packages/`): Grouped tasks for coordinated execution
- **Tasks** (`docs/planning/tasks/`): Individual actionable items with state tracking

**State Management:**
- Tasks flow through states: `draft` → `ready` → `in_progress` → `done`
- State changes are logged to `.audiagentic/planning/events/events.jsonl`
- Each artifact has unique ID (e.g., `task-0258`, `spec-0050`)

**Core Components:**
- Planning module in `src/audiagentic/planning/`
- Event system for audit logging
- Validation and reconciliation tools
- CLI commands for artifact management

**Integration Points:**
- Knowledge component syncs from planning events
- MCP server exposes planning operations
- Codex prompt trigger bridge for tagged prompts

## How to use
**Create artifacts:**
```bash

## Create a new request
audiagentic planning new-request --label "My Request" --summary "Brief description"

## Create a specification
audiagentic planning new-spec --label "My Spec" --summary "What this specifies"

## Create a plan
audiagentic planning new-plan --label "My Plan" --spec spec-XXXX
```

**Manage tasks:**
```bash

## List ready tasks
audiagentic planning next-tasks --state ready

## Change task state
audiagentic planning state --id task-XXXX --new-state in_progress

## View task status
audiagentic planning show --id task-XXXX
```

**Workflow:**
1. Capture work as a request
2. Create specification detailing the solution
3. Create plan linking to specification
4. Create work package with tasks
5. Execute tasks, updating state as you progress
6. Events are automatically logged for knowledge sync

## Sync notes
This page should be refreshed when:
- New artifact types are added to the planning system
- State machine transitions change
- Event schema is modified
- CLI commands are added or removed

**Sources:**
- `src/audiagentic/planning/` - Core implementation
- `.audiagentic/planning/events/events.jsonl` - Event log
- `docs/planning/` - Artifact storage

**Sync frequency:** On planning system changes

## References
- [Getting Started Guide](../guides/guide-getting-started.md)
- [Using the Planning System](../guides/guide-using-planning.md)
- [Planning Module Review Summary](../../docs/planning/docs/PLANNING_REVIEW_SUMMARY.md)
- [Critical Fixes Specification](../../docs/planning/specifications/spec-0054-planning-module-critical-fixes-specification.md)
- [Planning CLI Tool](../tools/tool-cli.md)
- Event log: `.audiagentic/planning/events/events.jsonl`
