---
id: standard-0013
label: Event subscription configuration standard
state: ready
summary: Standard format for event subscription/pub configuration that can be reused
  across components, aligning with spec-0055 event layer protocol.
---


# Standard

Standard format for event subscription and publication configuration in AUDiaGentic-based projects. Enables components to define event handling behavior in configuration files rather than code, supporting the event-driven architecture defined in spec-019.

# Source Basis

This standard is derived from:
- spec-019 (Interoperability event layer specification) — event protocol and envelope format
- standard-0011 (Component architecture standard) — config-driven design requirements
- Existing knowledge event adapter patterns — practical implementation experience

# Purpose

1. **Separation of concerns**: Event capture (adapters) vs event response (handlers)
2. **Config-driven behavior**: All event handling logic in YAML, not code
3. **Reusability**: Standard format usable across knowledge, planning, and future components
4. **Extensibility**: New event types and handlers added via config, not code changes

# Event Configuration Structure

## Two-file pattern

Event configuration uses two complementary files:

1. **Adapters** (`adapters.yml`): Define what events to capture and from where
2. **Handlers** (`handlers.yml`): Define what actions to take when events are captured

This separation allows:
- Multiple adapters to trigger the same handler
- Multiple handlers to respond to the same event (priority-based)
- Independent evolution of event sources and event responses

## Adapters configuration

Adapters define event sources and capture rules:

```yaml
# adapters.yml
adapters:
  - id: <unique-adapter-id>
    name: <human-readable-name>
    description: <purpose-of-this-adapter>
    
    # Event source definition
    source_kind: event_stream | file_watch | manual
    
    # For event_stream sources:
    path_globs:
      - <path-pattern-to-event-files>
    
    # Event matching
    event_name_patterns:
      - <event-type-pattern>
    
    # Payload filtering (optional)
    payload_filters:
      equals:
        <field>: <value>
      in:
        <field>:
          - <value1>
          - <value2>
      not_equals:
        <field>: <value>
    
    # Metadata (optional)
    status_field: <field-name-for-status>
    summary_fields:
      - <field-name>
    summary_prefix: <template-string>
    
    # Affected resources (component-specific)
    affects_pages:
      - <page-id>
    
    # Handler reference (optional, defaults to handler config)
    action: <action-name>
    action_args:
      <arg-name>: <value>
    
    # Documentation
    note: |
      <multi-line documentation>
```

### Adapter fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `id` | Yes | string | Unique identifier for this adapter |
| `name` | Yes | string | Human-readable name |
| `description` | Yes | string | Purpose description |
| `source_kind` | Yes | string | Type of event source |
| `path_globs` | Conditional | array | File patterns for event_stream sources |
| `event_name_patterns` | Yes | array | Event type patterns to match |
| `payload_filters` | No | object | Filter events by payload content |
| `status_field` | No | string | Field name for status extraction |
| `summary_fields` | No | array | Fields to include in summary |
| `summary_prefix` | No | string | Template for summary generation |
| `affects_pages` | No | array | Page IDs affected (knowledge-specific) |
| `action` | No | string | Action to trigger |
| `action_args` | No | object | Action arguments |
| `note` | No | string | Documentation |

## Handlers configuration

Handlers define event response behavior:

```yaml
# handlers.yml
# Default handler when no pattern matches
default_handler: deterministic | review_only | none

handlers:
  - # Event matching
    event_patterns:
      - <event-type-pattern>
    
    # Payload filtering (optional)
    payload_filters:
      equals:
        <field>: <value>
      in:
        <field>:
          - <value1>
    
    # Handler type
    handler: deterministic | review_only | none
    
    # Action to execute
    action: <action-name>
    action_args:
      <arg-name>: <value>
    
    # Priority (optional, higher = first)
    priority: <integer>
    
    # Documentation
    note: |
      <multi-line documentation>
```

### Handler fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `event_patterns` | Yes | array | Event type patterns to match |
| `payload_filters` | No | object | Filter by payload content |
| `handler` | Yes | string | Handler type (deterministic/review_only/none) |
| `action` | Conditional | string | Action to execute (required if handler != none) |
| `action_args` | No | object | Action arguments |
| `priority` | No | integer | Execution priority (higher first, default 0) |
| `note` | No | string | Documentation |

### Handler types

| Type | Description | Auto-apply |
|------|-------------|------------|
| `deterministic` | Safe, predictable updates | Yes |
| `review_only` | Queue for manual/agent review | No |
| `none` | Capture event, no action | N/A |

## Payload filters

Standard filter operators for both adapters and handlers:

```yaml
payload_filters:
  # Exact match
  equals:
    field_name: value
    
  # In list
  in:
    field_name:
      - value1
      - value2
      
  # Not equal
  not_equals:
    field_name: value
    
  # Not in list
  not_in:
    field_name:
      - value1
      
  # Numeric comparison
  gt:
    field_name: 10
  gte:
    field_name: 10
  lt:
    field_name: 10
  lte:
    field_name: 10
```

All filters are ANDed together. Any filter section (equals, in, etc.) is ORed within that section.

# Event Type Patterns

Event types follow spec-019 dot-notation: `{component}.{noun}.{verb}`

Pattern matching rules:
- Exact match: `planning.item.state.changed`
- Single-segment wildcard: `planning.item.*` matches `planning.item.state.changed` but not `planning.item.sub.changed`
- Legacy compatibility: `*.after_state_change` matches `task.after_state_change`

# Component-Specific Extensions

Components may extend the base format with additional fields:

## Knowledge component extensions

- `affects_pages`: Array of page IDs affected by this event
- `action`: Knowledge-specific actions (mark_stale, generate_sync_proposal, etc.)

## Planning component extensions

- `item_kind`: Filter by planning item kind (task, wp, plan, spec)
- `state_transitions`: Define allowed state transitions

# File Locations

Standard locations for event configuration:

```
# Runtime configuration (component-specific)
.audiagentic/<component>/events/adapters.yml
.audiagentic/<component>/events/handlers.yml

# Project documentation (optional, for reference)
docs/<component>/events/adapters.yml
docs/<component>/events/handlers.yml
```

Runtime config (`.audiagentic/`) takes precedence over documentation (`docs/`).

# Verification Expectations

1. **Config validity**: All event configs must be valid YAML with required fields present
2. **Pattern matching**: Event patterns must follow spec-019 dot-notation
3. **Handler types**: Only defined handler types (deterministic, review_only, none) are valid
4. **Action existence**: Referenced actions must be implemented in the component
5. **No code duplication**: Event handling logic must be in config, not duplicated in code

# Examples

## Example 1: Planning state change handler

```yaml
# handlers.yml
handlers:
  - event_patterns:
      - planning.item.state.changed
    payload_filters:
      in:
        new_state:
          - done
          - verified
    handler: deterministic
    action: mark_stale_and_generate_sync_proposal
    action_args:
      require_review: false
      proposal_mode: deterministic
    priority: 10
```

## Example 2: Review queue handler

```yaml
# handlers.yml
handlers:
  - event_patterns:
      - planning.item.state.changed
    payload_filters:
      equals:
        new_state: review
    handler: review_only
    action: generate_sync_proposal
    action_args:
      require_review: true
      proposal_mode: review_only
    priority: 5
    note: |
      Queues for agent review. Future: job/agent manager will assign work.
```

## Example 3: Knowledge adapter

```yaml
# adapters.yml
adapters:
  - id: planning-state-changes
    name: Planning State Change Bridge
    description: Consume planning state changes and update knowledge
    source_kind: event_stream
    path_globs:
      - .audiagentic/planning/events/events.jsonl
    event_name_patterns:
      - planning.item.state.changed
    payload_filters:
      in:
        new_state:
          - done
          - verified
    affects_pages:
      - system-planning
      - system-knowledge
    action: mark_stale_and_generate_sync_proposal
    action_args:
      require_review: false
      proposal_mode: deterministic
```

# Non-Goals

1. **Event schema validation**: This standard defines config format, not event payload schemas
2. **Agent assignment logic**: Job/agent manager is out of scope (future component)
3. **Event transport**: This standard is transport-agnostic (spec-019 defines transport)
4. **Real-time requirements**: This standard does not define latency or throughput requirements

# Migration Guide

## From hardcoded event handling

1. Extract event patterns from code into `adapters.yml`
2. Extract handler logic from code into `handlers.yml`
3. Update code to load and use config files
4. Remove hardcoded event handling logic

## From knowledge-specific format

1. Split combined adapter/handler configs into separate files
2. Update field names to match standard (e.g., `event_name` → `event_name_patterns`)
3. Add missing required fields (id, name, description)
4. Update action references to use standard action names

# Related Documents

- spec-019: Interoperability event layer specification
- standard-0011: Component architecture standard
- docs/knowledge/events/adapters.yml: Knowledge event adapters (example)
- docs/knowledge/events/handlers.yml: Knowledge event handlers (example)
