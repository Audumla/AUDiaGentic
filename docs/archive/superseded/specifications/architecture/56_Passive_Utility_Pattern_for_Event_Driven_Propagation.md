---
id: arch-056
label: Passive utility pattern for event-driven propagation
state: ready
summary: Architecture pattern for passive utility components in event-driven systems, ensuring clear ownership and swappable event bus implementations.
---

# Passive Utility Pattern for Event-Driven Propagation

## Overview

This document describes the **passive utility pattern** used in AUDiaGentic for event-driven state propagation and similar cross-cutting concerns. This pattern ensures:

1. **Clear ownership**: Components own their event handlers, not utility libraries
2. **Swappable event bus**: Event bus implementations can be replaced without modifying component code
3. **Testability**: Utilities can be tested in isolation without event infrastructure
4. **Separation of concerns**: Event routing is separate from business logic

## Problem Statement

Before implementing state propagation (task-0279), we identified several anti-patterns:

1. **Hardcoded config paths**: The propagation engine knew about planning's internal file structure (`.audiagentic/planning/config/state_propagation.yaml`)
2. **Event subscription coupling**: The propagation engine subscribed to events on behalf of planning, violating component boundaries
3. **Tight coupling**: The propagation engine called planning APIs directly AND subscribed to planning events, creating bidirectional dependencies

## Solution: Passive Utility Pattern

### Core Principles

1. **Utilities are passive**: They provide methods for calculating or applying changes but do NOT:
   - Subscribe to events
   - Trigger actions automatically
   - Know about other components' internal structure

2. **Owner components register handlers**: The component that owns a utility (e.g., planning owns the propagation engine) is responsible for:
   - Passing configuration paths to the utility
   - Registering event handlers that call the utility
   - Deciding when and how to apply the utility's suggestions

3. **Event bus is generic**: The event bus:
   - Knows nothing about specific event types or handlers
   - Provides a generic pub/sub interface (`EventBusProtocol`)
   - Can be replaced with external MQ systems (RabbitMQ, Kafka) without code changes

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Planning Component                        │
│  (Owner of propagation engine)                              │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  PlanningAPI                                          │  │
│  │                                                       │  │
│  │  def __init__(self):                                  │  │
│  │      # Pass config path to utility                   │  │
│  │      config_path = self.root / ".audiagentic" /      │  │
│  │                  "planning" / "config" /             │  │
│  │                  "state_propagation.yaml"            │  │
│  │      self._propagation_engine = StatePropagationEngine(
│  │          planning_api=self,
│  │          config_path=config_path,
│  │      )
│  │                                                       │  │
│  │      # Register event handler (planning owns this)   │  │
│  │      bus = get_bus()                                  │  │
│  │      bus.subscribe("planning.item.state.changed",    │  │
│  │                    self._on_state_change_for_propagation)
│  │                                                       │  │
│  │  def _on_state_change_for_propagation(self,          │  │
│  │                                        event_type,    │  │
│  │                                        payload,       │  │
│  │                                        metadata):      │  │
│  │      # Call passive utility to calculate propagations│  │
│  │      propagations = self._propagation_engine.        │  │
│  │                      propagate(item_id, new_state)    │  │
│  │                                                       │  │
│  │      # Apply each propagation                        │  │
│  │      for target_id, target_kind, target_state in     │  │
│  │          propagations:                                │  │
│  │          self._propagation_engine.apply_propagation(  │  │
│  │              target_id=target_id,                     │  │
│  │              target_state=target_state,               │  │
│  │              source_id=item_id,                       │  │
│  │              source_state=new_state,                  │  │
│  │              metadata=metadata,                       │  │
│  │          )                                            │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ Uses (passes config_path)
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              Interoperability Component                      │
│  (Provides passive utilities)                               │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  StatePropagationEngine (Passive Utility)            │  │
│  │                                                       │  │
│  │  def __init__(self, planning_api, config_path):      │  │
│  │      # Config path passed by owner, not hardcoded    │  │
│  │      self._config_path = config_path                 │  │
│  │      self._planning_api = planning_api               │  │
│  │                                                       │  │
│  │  def propagate(self, item_id, new_state):            │  │
│  │      # Calculate what should propagate (passive)     │  │
│  │      # Does NOT apply changes or subscribe to events │  │
│  │      return [(target_id, target_kind, target_state)] │  │
│  │                                                       │  │
│  │  def apply_propagation(self, target_id,              │  │
│  │                         target_state,                 │  │
│  │                         source_id, source_state,      │  │
│  │                         metadata):                    │  │
│  │      # Apply individual propagation                  │  │
│  │      # Called by owner component                     │  │
│  │      self._planning_api.state(...)                   │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                            │
                            │ Publishes/subscribes via
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    Event Bus                                 │
│  (Generic pub/sub, swappable)                               │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  EventBusProtocol (Interface)                        │  │
│  │                                                       │  │
│  │  def publish(event_type, payload, metadata, mode):   │  │
│  │      # Dispatch to matching handlers                 │  │
│  │      # Knows NOTHING about event types or handlers   │  │
│  │                                                       │  │
│  │  def subscribe(pattern, handler):                    │  │
│  │      # Register handler for pattern                  │  │
│  │      # Returns SubscriptionHandle                    │  │
│  │                                                       │  │
│  │  def unsubscribe(handle):                            │  │
│  │      # Remove handler                                │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                              │
│  Implementations:                                            │
│  - EventBus (in-process, default)                           │
│  - ExternalMQBus (RabbitMQ, Kafka, etc.)                    │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Details

### 1. StatePropagationEngine (Passive Utility)

**Location**: `src/audiagentic/planning/app/propagation.py` (moved from interoperability in task-0279 refactor)

**Key characteristics**:
- Accepts `config_path` parameter from owner component (not hardcoded)
- Provides `propagate()` method that calculates propagations (does NOT apply them)
- Provides `apply_propagation()` method that applies individual propagations
- Does NOT subscribe to events
- Does NOT know about planning's internal file structure
- Uses `PlanningAPIInterface` protocol for loose coupling (see `propagation_interface.py`)
- Completely config-driven: all rules and actions loaded from config file

**Usage**:
```python
# In PlanningAPI.__init__:
config_path = self.root / ".audiagentic" / "planning" / "config" / "state_propagation.yaml"
self._propagation_engine = StatePropagationEngine(
    planning_api=self,
    config_path=config_path,
)
```

### 2. PlanningAPI (Owner Component)

**Location**: `src/audiagentic/planning/app/api.py`

**Key characteristics**:
- Passes config path to propagation engine
- Registers event handler `_on_state_change_for_propagation`
- Calls `propagate()` to get suggestions
- Calls `apply_propagation()` for each suggestion
- Owns the subscription handle and can unsubscribe if needed

**Usage**:
```python
# In PlanningAPI.__init__:
bus = get_bus()
self._propagation_subscription = bus.subscribe(
    "planning.item.state.changed",
    self._on_state_change_for_propagation,
)

# Event handler:
def _on_state_change_for_propagation(self, event_type, payload, metadata):
    propagations = self._propagation_engine.propagate(item_id, new_state)
    for target_id, target_kind, target_state in propagations:
        self._propagation_engine.apply_propagation(
            target_id=target_id,
            target_state=target_state,
            source_id=item_id,
            source_state=new_state,
            metadata=metadata,
        )
```

### 3. EventBus (Generic Pub/Sub)

**Location**: `src/audiagentic/interoperability/bus.py`

**Key characteristics**:
- Implements `EventBusProtocol` interface
- Knows nothing about specific event types or handlers
- Supports wildcard pattern matching (`*` and `**`)
- Supports SYNC and ASYNC delivery modes
- Isolates handler failures (one failure doesn't affect others)
- Detects cycles via `propagation_depth` and `correlation_id`

**Swappability**:
```python
# Default in-process implementation:
from audiagentic.interoperability import get_bus
bus = get_bus()  # Returns EventBus instance

# External MQ implementation (hypothetical):
from audiagentic.interoperability import ExternalMQBus
bus = ExternalMQBus(rabbitmq_url="amqp://...")
# Register as default:
set_bus(bus)
```

## Benefits

### 1. Clear Ownership

- Planning component owns the propagation engine and decides when to use it
- Planning component owns the event subscription and can unsubscribe if needed
- No ambiguity about who is responsible for what

### 2. Testability

- `StatePropagationEngine` can be tested in isolation with mock `planning_api`
- Event handlers can be tested without event bus infrastructure
- Event bus can be tested with mock handlers

### 3. Swappability

- Event bus implementations can be replaced without modifying component code
- Components only depend on `EventBusProtocol` interface
- External MQ systems (RabbitMQ, Kafka) can be drop-in replacements

### 4. Separation of Concerns

- Event routing (event bus) is separate from business logic (propagation rules)
- Configuration management (planning) is separate from propagation calculation (interoperability)
- Each component has a single, clear responsibility

## Verification

### Tests

1. **Propagation tests** (`tests/integration/test_propagation.py`):
   - Test state propagation across hierarchy levels
   - Test propagation with disabled flags
   - Test cycle detection with max depth
   - Test failure isolation

2. **Healing tests** (`tests/integration/test_healing.py`):
   - Test validation of state consistency
   - Test healing suggestions and auto-fix

3. **Event bus tests** (existing tests in `tests/`):
   - Test pattern matching
   - Test SYNC/ASYNC delivery
   - Test handler isolation
   - Test cycle detection

### Standards Compliance

This pattern complies with:

- **Standard-0011 (Component Architecture)**:
  - Rule #17: Components must not hardcode paths to other components' config
  - Rule #24: Components must not subscribe to events on behalf of other components
  - Rule #25: Utility components must be passive
  - Rule #26: Event bus must remain ignorant of specific event types
  - Rule #27: Event bus implementations must be swappable

## Config-Driven Rule System

The propagation engine uses a completely config-driven architecture for rules and actions:

### Architecture

```
Config File (.audiagentic/planning/config/state_propagation.yaml)
    │
    ├── kinds:
    │   └── task:
    │       └── state_rules:
    │           └── done:
    │               ├── rule: "trigger_parent_if_ready"  ← Rule name
    │               └── actions: ["check_request_completion"]  ← Action names
    │
    ├── rules:
    │   └── trigger_parent_if_ready:
    │       ├── enabled: true
    │       ├── logic: "audiagentic.planning.app.propagation_rules.rule_trigger_parent_if_ready"
    │       └── description: "Trigger parent if parent is in ready state"
    │
    └── actions:
        └── check_request_completion:
            ├── enabled: true
            ├── logic: "audiagentic.planning.app.propagation_rules.action_check_request_completion"
            └── description: "Auto-complete requests when all specs are done"

Runtime:
    1. Engine loads config
    2. For each rule/action, imports logic function from module reference
    3. Stores callable in config dict
    4. When propagate() is called, executes the callable
```

### Benefits

1. **No hardcoded rules**: All business logic is in config, not code
2. **Pluggable implementations**: New rules/actions added by creating new functions and updating config
3. **Easy to understand**: Config file shows all rules at a glance
4. **Testable**: Each rule/action function can be tested independently
5. **Workflow-agnostic**: Different workflows can use different config files

### Adding New Rules

1. Create rule function in `propagation_rules.py`:
   ```python
   def rule_my_custom_rule(engine, child_id, parent_id, new_state) -> bool:
       """Return True if state should propagate."""
       # Custom logic here
       return True
   ```

2. Add to config:
   ```yaml
   rules:
     my_custom_rule:
       enabled: true
       logic: "audiagentic.planning.app.propagation_rules.rule_my_custom_rule"
       description: "My custom rule"
   ```

3. Reference in state rules:
   ```yaml
   kinds:
     task:
       state_rules:
         my_state:
           rule: "my_custom_rule"
           new_state: "ready"
   ```

## Safety Mechanisms

The propagation engine includes several safety mechanisms to prevent infinite loops and performance issues:

### 1. Max Depth Enforcement

- **Purpose**: Prevent infinite propagation cycles if rules form circular dependencies
- **Implementation**: `_get_max_depth()` returns configured max depth (default: 10)
- **Enforcement points**:
  - `propagate()`: Checks depth before calculating propagations
  - `apply_propagation()`: Checks depth before applying changes
- **Behavior**: If depth exceeds max, propagation is skipped with warning logged
- **Config**: Set via `global.max_depth` in config file

### 2. Healing Fix Flag

- **Purpose**: Prevent healing fixes from triggering normal propagation (avoiding loops)
- **Implementation**: `propagate()` checks `metadata.get("healing_fix")` flag
- **Behavior**: If flag is True, propagation is skipped entirely
- **Usage**: Healing fixes call `state(healing_fix=True)` which sets the flag in metadata

### 3. Config Caching

- **Purpose**: Avoid repeated config file reads on every propagation call
- **Implementation**: `self._config` cached after first successful load
- **Error handling**: Config is assigned even on error path to prevent repeated failed loads
- **State tracking**: Uses `None` vs `dict` sentinel values (not empty dict) for proper state tracking

### 4. Cycle Detection

- **Purpose**: Detect and prevent propagation cycles
- **Implementation**: Event bus tracks `propagation_depth` and `correlation_id` in metadata
- **Behavior**: Cycles are detected when same item is visited multiple times in same propagation chain

## Performance Characteristics

### Known Costs

1. **Reverse parent lookup** (`_find_reverse_parents()`):
   - **Complexity**: O(n) where n = total items in planning database
   - **Reason**: Scans all items to find those with given item as parent
   - **Mitigation**: Consider adding indexed lookup in PlanningAPI for large projects
   - **Impact**: Acceptable for small/medium projects (<1000 items), may need optimization for large projects

2. **Config loading**:
   - **Complexity**: O(1) after first load (cached)
   - **First load**: File I/O + YAML parsing + function imports
   - **Subsequent loads**: Instant (cached dict)

3. **Propagation calculation**:
   - **Complexity**: O(p * r) where p = number of parents/children, r = number of rules
   - **Typical case**: p < 5, r < 10, so very fast
   - **Worst case**: Deep hierarchies with many rules

### Optimization Opportunities

1. **Indexed reverse parent lookup**: Add parent index in PlanningAPI to make `_find_reverse_parents()` O(1)
2. **Propagation metrics**: Track propagation success/failure rates and depth statistics
3. **Lazy rule loading**: Load rule functions on first use instead of config load time

## Future Work

1. **External MQ implementation**: Implement `ExternalMQBus` for RabbitMQ/Kafka
2. **CLI healing command**: Add CLI command to run healing on entire project
3. **Propagation metrics**: Add metrics for propagation success/failure rates and depth statistics
4. **Config validation**: Add runtime validation of propagation config
5. **Indexed parent lookup**: Add parent index in PlanningAPI for O(1) reverse lookups

## References

- [Standard-0011: Component Architecture Standard](../planning/standards/standard-0011-component-architecture-standard.md)
- [Task-0279: State Propagation Engine](../../../.audiagentic/planning/tasks/task-0279-state-propagation-engine.md)
- [Event Bus Implementation](../../../../src/audiagentic/interoperability/bus.py)
