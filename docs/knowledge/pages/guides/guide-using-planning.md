## Summary
This guide explains how to use the AUDiaGentic planning system to manage software engineering work. It covers creating artifacts, managing task workflows, and integrating with the knowledge component.

## Current state
**Artifact Hierarchy:**
```
Request (problem/opportunity)
  └── Specification (technical solution)
        └── Plan (implementation approach)
              └── Work Package (grouped tasks)
                    └── Tasks (actionable items)
```

**Task States:**
- `draft`: Initial creation, not ready for work
- `ready`: Prepared for execution
- `in_progress`: Currently being worked on
- `done`: Completed and verified

**Event Logging:**
All state changes and creations are logged to `.audiagentic/planning/events/events.jsonl` with timestamps and details.

## How to use
**Creating Artifacts:**

1. **Create a Request** (capture work):
```bash

## Via CLI
audiagentic planning new-request \
  --label "Add Feature X" \
  --summary "Implement feature X to solve problem Y"

## Output: request-XXXX created in docs/planning/requests/
```

2. **Create a Specification** (define solution):
```bash
audiagentic planning new-spec \
  --label "Feature X Specification" \
  --summary "Technical specification for feature X" \
  --request-refs request-XXXX
```

3. **Create a Plan** (organize implementation):
```bash
audiagentic planning new-plan \
  --label "Feature X Implementation Plan" \
  --summary "Plan for implementing feature X" \
  --spec spec-XXXX
```

4. **Create Tasks** (actionable items):
```bash

## Tasks can be created individually or packaged
audiagentic planning new-task \
  --label "Implement component A" \
  --summary "Build component A as specified" \
  --spec spec-XXXX
```

**Managing Tasks:**

```bash

## View ready tasks
audiagentic planning next-tasks --state ready

## Claim a task (mark as in_progress)
audiagentic planning state \
  --id task-XXXX \
  --new-state in_progress \
  --reason "Starting work on this task"

## Complete a task
audiagentic planning state \
  --id task-XXXX \
  --new-state done \
  --reason "Implementation complete, tests passing"

## View task details
audiagentic planning show --id task-XXXX
```

**Work Packages:**
Group related tasks for coordinated execution:
```bash
audiagentic planning package \
  --plan plan-XXXX \
  --tasks task-AAAA task-BBBB task-CCCC \
  --label "Work Package Alpha" \
  --summary "Coordinated work on related tasks"
```

**Event-Driven Knowledge Sync:**
When tasks are completed, events are automatically:
1. Logged to `events.jsonl`
2. Processed by knowledge component (if configured)
3. May generate sync proposals in `docs/knowledge/proposals/`

**Best Practices:**
- Keep summaries concise (1-2 sentences)
- Use clear, descriptive labels
- Link artifacts properly (spec → request, plan → spec, task → spec)
- Update task states promptly
- Include meaningful reasons for state changes

## Sync notes
This page should be refreshed when:
- New artifact types are added
- State machine transitions change
- CLI commands are modified
- Event schema changes

**Sources:**
- `src/audiagentic/planning/` - Core implementation
- CLI command definitions
- Event schema in event log

**Sync frequency:** On planning system API changes

## References
- [Planning System](../systems/system-planning.md)
- [Getting Started](./guide-getting-started.md)
- [CLI Tool](../tools/tool-cli.md)
- Event log: `.audiagentic/planning/events/events.jsonl`
