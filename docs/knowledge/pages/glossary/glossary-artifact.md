---
id: glossary-artifact
title: Artifact
type: glossary_term
status: current
summary: Any document managed by the AUDiaGentic planning system, representing work items at different levels of abstraction from requests to tasks
owners:
- core-team
updated_at: '2026-04-15'
tags:
- glossary
- planning
- terminology
related:
- system-planning
- glossary-current-state
---

## Summary
An **artifact** is any document managed by the AUDiaGentic planning system. Artifacts represent work items at different levels of abstraction, from high-level requests to actionable tasks. Each artifact has a unique ID, YAML frontmatter metadata, and markdown content.

## Current state
**Artifact Types:**

| Type | ID Prefix | Location | Purpose |
|------|-----------|----------|---------|
| Request | `request-XXXX` | `docs/planning/requests/` | Capture problems, opportunities, or work items |
| Specification | `spec-XXXX` | `docs/planning/specifications/` | Define technical solutions in detail |
| Plan | `plan-XXXX` | `docs/planning/plans/` | Organize implementation approach |
| Work Package | `wp-XXXX` | `docs/planning/work-packages/` | Group related tasks for coordinated execution |
| Task | `task-XXXX` | `docs/planning/tasks/` | Individual actionable items |

**Artifact Structure:**
```yaml
---
id: task-0258
label: Task Label
state: ready
summary: Brief description
spec_ref: spec-0050
request_refs:
  - request-0032
standard_refs:
  - standard-0005
---

# Description
Detailed description content...

# Acceptance Criteria
Criteria for completion...

# Notes
Additional notes...
```

**Lifecycle:**
1. Created with unique ID (auto-incremented)
2. Stored as markdown file with YAML frontmatter
3. Events logged on creation and state changes
4. Linked to related artifacts via reference fields
5. May be superseded or cancelled

**Event Logging:**
All artifact operations generate events:
- `*.after_create`: Artifact created
- `*.after_state_change`: State transition
- Events stored in `.audiagentic/planning/events/events.jsonl`

## How to use
**Referencing Artifacts:**
- Use full ID: `task-0258`, `spec-0050`
- Link in markdown: `[task-0258](../../planning/tasks/core/task-0258.md)`
- Reference in frontmatter: `spec_ref: spec-0050`

**Querying Artifacts:**
```bash
# Show artifact details
audiagentic planning show --id task-0258

# List artifacts by kind
audiagentic planning list --kind task

# Find ready tasks
audiagentic planning next-tasks --state ready
```

**Best Practices:**
- Keep IDs immutable once created
- Use descriptive labels (human-readable)
- Write concise summaries (1-2 sentences)
- Link artifacts properly (bidirectional when possible)
- Update state promptly as work progresses

## Sync notes
This page should be refreshed when:
- New artifact types are added
- Artifact schema changes
- ID naming conventions change
- Event types are modified

**Sources:**
- `src/audiagentic/planning/` - Planning module
- Artifact file templates
- Event schema definitions

**Sync frequency:** On planning system schema changes

## References
- [Planning System](../systems/system-planning.md)
- [Using the Planning System](../guides/guide-using-planning.md)
- [Glossary: Current State](./glossary-current-state.md)
