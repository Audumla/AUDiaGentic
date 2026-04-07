# tm (Task Manager) Skill for AUDiaGentic Planning

## Overview

The `tm` system manages requests, specifications, plans, tasks, work packages, and standards.

## Agent Access

### Option 1: MCP (Recommended for All Providers)

**Setup once per provider**, then use clean function calls forever.

**Add to provider config:**

**Opencode** (`opencode.json`):
```json
{
  "mcp": {
    "audiagentic-planning": {
      "type": "local",
      "command": ["python", "tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py"],
      "enabled": true
    }
  }
}
```

**Claude** (`~/.claude/mcp.json`):
```json
{
  "mcpServers": {
    "audiagentic-planning": {
      "command": "python",
      "args": ["tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py"]
    }
  }
}
```

**Gemini** (`~/.gemini/mcp.json`):
```json
{
  "mcpServers": {
    "audiagentic-planning": {
      "command": "python",
      "args": ["tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py"]
    }
  }
}
```

**Then use tools directly:**
```python
tm_new_task("Label", "Summary", "spec-0001", "core")
tm_state("task-0001", "ready")
tm_next_tasks("core")
```

### Option 2: Python Helper (No Setup)

Use the Python helper for minimal token usage:

```python
import tools.planning.tm_helper as tm

# Create objects
tm.new_task("Label", "Summary", spec="spec-0001", domain="core")
tm.new_spec("Label", "Summary", request_refs=["request-0001"])

# Lifecycle
tm.state("task-0001", "ready")
tm.move("task-0001", "spec-migration")

# Queries
tasks = tm.next_tasks(domain="core")  # [{"id": ..., "label": ..., "path": ...}]
tm.validate()  # [] or list of errors
```

## CLI Access

```bash
python tools/planning/tm.py <command> [options]
```

Auto-detects project root from cwd, or use `--root <path>`.

## Core Commands

### Create Objects

```bash
# Request - raw requirement capture
tm new request --label "<label>" --summary "<summary>"

# Specification - detailed technical spec
tm new spec --label "<label>" --summary "<summary>" [--request-ref <id>]

# Plan - delivery plan
tm new plan --label "<label>" --summary "<summary>" [--spec <id>]

# Task - individual work item (requires spec)
tm new task --label "<label>" --summary "<summary>" --spec <id> [--domain <domain>] [--target <target>]

# Work package - grouped tasks (requires plan)
tm new wp --label "<label>" --summary "<summary>" --plan <id> [--domain <domain>]

# Standard - reusable standard/template
tm new standard --label "<label>" --summary "<summary>"
```

### Lifecycle Management

```bash
# Change state (validates transitions)
tm state <id> <new_state>

# Move task/wp to different domain
tm move <id> --domain <domain>

# Update label/summary/body
tm update <id> [--label <label>] [--summary <summary>] [--append <text>]
```

### Relationships

```bash
# Link objects
tm relink <src_id> <field> <dst_id> [--seq <num>] [--display <label>]

# Fields: request_refs, spec_refs, standard_refs, plan_ref, spec_ref, 
#         parent_task_ref, task_refs, work_package_refs

# Create work package from tasks
tm package --plan <id> --task <id1> --task <id2> ... --label "<label>" --summary "<summary>" [--domain <domain>]
```

### Queries

```bash
# List objects
tm list [kind]  # kinds: request, spec, plan, task, wp, standard

# Show object details
tm show <id>

# Next available items
tm next [kind] [--state <state>] [--domain <domain>]

# Status summary by kind/state
tm status

# Relationship trace
tm trace

# Extract object with context
tm extract <id> [--with-related] [--with-resources]

# Effective standards for object
tm standards <id>
```

### Claims (Task Assignment)

```bash
# Claim a task
tm claim task <id> --holder <holder> [--ttl <seconds>]

# Release a claim
tm unclaim <id>

# List claims
tm claims [kind]
```

### Maintenance

```bash
# Validate all objects
tm validate

# Rebuild indexes
tm index

# Reconcile (fix filenames, find orphans)
tm reconcile

# Seed counters from existing docs (run once after install)
tm sync-counters
```

### Events & Hooks

```bash
# Recent events
tm events [--tail <n>]

# Hook configuration
tm hooks
```

## Common Workflows

### Create a Complete Planning Chain

```bash
# 1. Create request
tm new request --label "Feature X" --summary "Implement feature X"

# 2. Create spec linked to request
tm new spec --label "Feature X spec" --summary "Technical spec for X" --request-ref request-0001

# 3. Create plan linked to spec
tm new plan --label "Feature X plan" --summary "Delivery plan for X" --spec spec-0001

# 4. Create tasks linked to spec
tm new task --label "Task A" --summary "Do A" --spec spec-0001 --domain core
tm new task --label "Task B" --summary "Do B" --spec spec-0001 --domain core

# 5. Link tasks to spec
tm relink spec-0001 task_refs task-0001 --seq 1000
tm relink spec-0001 task_refs task-0002 --seq 2000

# 6. Create work package
tm package --plan plan-0001 --task task-0001 --task task-0002 --label "WP A" --summary "Work package A" --domain core

# 7. Link WP to plan
tm relink plan-0001 work_package_refs wp-0001 --seq 1000

# 8. Validate
tm validate
```

### Migration Workflow Pattern

```bash
# For each doc to migrate:
# 1. Create task for migration
tm new task --label "Migrate <doc>" --summary "<description>" --spec <migration-spec> --domain <domain>

# 2. Mark ready when spec complete
tm state <task-id> ready

# 3. Claim before working
tm claim task <task-id> --holder "<agent>"

# 4. Update with progress
tm update <task-id> --append "Migration notes..."

# 5. Mark done when complete
tm state <task-id> done

# 6. Release claim
tm unclaim <task-id>
```

## State Machines

### Request
```
captured → distilled → closed/superseded
```

### Spec/Plan/Task
```
draft → ready → in_progress → blocked → done
              ↓              ↓
           cancelled      cancelled
```

### Work Package
```
draft → ready → in_progress → review → done
              ↓              ↓         ↓
           cancelled      blocked   cancelled
```

## Best Practices

1. **Always validate** after bulk operations: `tm validate`
2. **Use domains** for tasks/WPs to isolate work streams
3. **Claim tasks** before modifying to prevent conflicts
4. **Use seq values** (1000, 2000, ...) for ordered refs - allows insertion
5. **Run index** after major changes for query accuracy
6. **Check events** for audit trail: `tm events --tail 50`

## Exit Codes

- `0`: Success
- `1`: Validation errors or failures
