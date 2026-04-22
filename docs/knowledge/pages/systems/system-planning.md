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
- Planning API (`src/audiagentic/planning/app/api.py`): Main API for artifact operations
- Config (`src/audiagentic/planning/app/config.py`): Configuration management
- Validation (`src/audiagentic/planning/app/val_mgr.py`): Schema validation
- Events (`src/audiagentic/planning/app/events.py`): Event logging
- Standards (`src/audiagentic/planning/app/standards.py`): Standards management
- Filesystem (`src/audiagentic/planning/fs/`): Read/write/scan operations
- Domain (`src/audiagentic/planning/domain/`): Models and states
- Planning MCP (`tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py`): Agent-facing mutation/query surface

**Integration Points:**
- Knowledge component syncs from planning events
- Interoperability event bus publishes state changes
- Execution system creates planning artifacts from jobs
- Runtime system tracks planning-related state

## How to use
**Create artifacts:**
```python
## Create a new request
tm_create(kind="request", label="My Request", summary="Brief description")

## Create a specification
tm_create(kind="spec", label="My Spec", summary="What this specifies", request_refs=["request-XXXX"])

## Create a plan
tm_create(kind="plan", label="My Plan", summary="Implementation plan", spec="spec-XXXX")
```

**Manage tasks:**
```python
## List ready tasks
tm_list(kind="task", state="ready")

## Change task state
tm_edit(id="task-XXXX", operations=[{"op": "state", "value": "in_progress"}])

## View task status
tm_get(id="task-XXXX")
```

**Agent mutation guidance:**
- Prefer `tm_edit` for single-item mutations
- Use `field` operations in `tm_edit` for top-level frontmatter refs/lists such as `spec_refs`, `request_refs`, `task_refs`, `work_package_refs`, and scalar refs like `spec_ref`
- Use `meta` operations only for nested `meta.*` values
- Use `tm_docs op=config` before `tm_create` so agents learn the live create contract without trial and error
- State-based section requirements are config-owned. Validator reads `profiles.yaml` `state_section_requirements`; do not hardcode section names or workflow-specific doc rules into agent logic

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
- [Knowledge System](./system-knowledge.md)
- [Execution System](./system-execution.md)
- [Runtime System](./system-runtime.md)
- [Interoperability System](./system-interoperability.md)
- [CLI Tool](../tools/tool-cli.md)
- Event log: `.audiagentic/planning/events/events.jsonl`
