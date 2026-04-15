# Auto-State Propagation Guide

## Overview

AUDiaGentic supports automatic state propagation across planning hierarchies. When enabled, state changes in child items automatically propagate to parent items based on configurable rules.

## Hierarchy

```
Request
  └── Spec
      └── Plan
          └── WP (Work Package)
              └── Task
```

State propagates upward: Task → WP → Plan → Spec → Request

## Global Configuration

Edit `.audiagentic/interoperability/state_propagation.yaml`:

```yaml
global:
  enabled: true  # Enable propagation by default
  max_depth: 10  # Maximum propagation chain depth
  default_mode: async  # async or sync

kinds:
  task:
    enabled: true  # Enable for tasks
  wp:
    enabled: true  # Enable for WPs
  plan:
    enabled: true  # Enable for plans
  spec:
    enabled: true  # Enable for specs
  request:
    enabled: false  # Disabled by default (requests are top-level)
```

## Per-Item Configuration

Override propagation settings for specific items by adding `propagation` to the item frontmatter:

```yaml
---
id: wp-0001
label: "Critical Work Package"
state: ready
propagation:
  enabled: false  # Disable propagation for this item
---
```

Or customize rules:

```yaml
---
id: task-0042
label: "Blocker Task"
state: ready
propagation:
  enabled: true
  rules:
    on_done: trigger_parent_done  # Force parent done when this task completes
---
```

## Default Propagation Rules

### Task → WP

- **Task in_progress** → WP in_progress (if WP is ready)
- **All tasks done** → WP done
- **Any task blocked** → WP blocked (unless WP is terminal)

### WP → Plan

- **WP in_progress** → Plan in_progress (if Plan is ready)
- **All WPs done** → Plan done
- **Any WP blocked** → Plan blocked (unless Plan is terminal)

### Plan → Spec

- **Plan in_progress** → Spec in_progress (if Spec is ready)
- **All plans done** → Spec done
- **Any plan blocked** → Spec blocked (unless Spec is terminal)

### Spec → Request (Auto-Complete)

- **All specs done** → Request done (if Request is not terminal)

## Disabling Propagation

### Globally

```yaml
global:
  enabled: false  # Disable all propagation
```

### Per-Kind

```yaml
kinds:
  task:
    enabled: false  # Disable for all tasks
```

### Per-Item

Add to item frontmatter:

```yaml
---
id: task-0042
propagation:
  enabled: false
---
```

## Use Cases

### 1. Auto-Complete Work Packages

Enable propagation (default) to automatically mark WPs as done when all tasks complete:

```yaml
---
id: wp-0001
label: "API Implementation"
state: ready
task_refs:
  - ref: task-0010
  - ref: task-0011
  - ref: task-0012
---
```

When all three tasks are marked `done`, the WP automatically becomes `done`.

### 2. Prevent Auto-Completion for Manual Review

Disable propagation for WPs that require manual review:

```yaml
---
id: wp-0002
label: "Security Audit"
state: ready
propagation:
  enabled: false  # Manual state management required
task_refs:
  - ref: task-0020
  - ref: task-0021
---
```

### 3. Auto-Complete Requests

Enable request auto-completion in global config:

```yaml
kinds:
  request:
    enabled: true  # Auto-complete when all specs done
```

When all specs for a request are `done`, the request automatically becomes `done`.

### 4. Blocker Tasks

A blocked task automatically blocks its parent WP, Plan, and Spec:

```yaml
---
id: task-0030
label: "Awaiting API Keys"
state: blocked
---
```

This propagates up: WP → Plan → Spec all become `blocked`.

## Logging

Propagation events are logged to `.audiagentic/planning/meta/propagation_log.json`:

```json
[
  {
    "timestamp": "2026-04-15T10:30:00Z",
    "source_kind": "task",
    "source_id": "task-0010",
    "target_kind": "wp",
    "target_id": "wp-0001",
    "old_state": "ready",
    "new_state": "in_progress",
    "triggered_by": "automatic",
    "propagation_depth": 1,
    "status": "success"
  }
]
```

## Troubleshooting

### Propagation Not Working

1. Check global config: `global.enabled` should be `true`
2. Check per-kind config: `kinds.<kind>.enabled` should be `true`
3. Check per-item config: Ensure `propagation.enabled` is not `false`
4. Check propagation log: `.audiagentic/planning/meta/propagation_log.json`

### Unwanted Propagation

Disable for specific items:

```yaml
---
id: task-0042
propagation:
  enabled: false
---
```

### Cycle Detection

Propagation stops at `max_depth` (default: 10) to prevent infinite loops. Check the propagation log for `propagation_depth` values.
