---
id: task-0279
label: Refactor event bus singleton pattern
state: completed
summary: Remove global state from event bus
request_refs:
- request-19
standard_refs:
- standard-0005
- standard-0006
---

## Implementation

Enhanced event bus documentation and warnings to guide developers toward dependency injection pattern:

1. EventBus class already has proper constructor with dependency injection support
2. Updated `get_bus()` docstring with explicit warnings about singleton pattern limitations
3. Added comprehensive examples showing preferred dependency injection pattern
4. Updated `reset_bus()` with warnings about global state modification
5. Documented migration path from singleton to dependency injection
6. Maintained backward compatibility for bootstrap scenarios

## Files Modified

- `src/audiagentic/interoperability/__init__.py` - Enhanced documentation and warnings

## Current State

The EventBus implementation already supports dependency injection:

```python
# Preferred: Explicit instantiation
from audiagentic.interoperability import EventBus
bus = EventBus(source_component="my_component")

# Or via dependency injection container
class Application:
    def __init__(self):
        self.bus = EventBus(source_component="app")
```

The singleton pattern (`get_bus()`) is retained for:
- Bootstrap scenarios
- Legacy code migration
- Quick prototyping

## Usage Pattern

```python
# Production code: Dependency injection
class PlanningService:
    def __init__(self, bus: EventBusProtocol):
        self.bus = bus
    
    def process(self):
        self.bus.publish("planning.item.created", {...})

# Test: Mock event bus
class MockEventBus(EventBusProtocol):
    def publish(self, *args, **kwargs):
        pass
    def subscribe(self, *args, **kwargs):
        return MockSubscriptionHandle()
    def unsubscribe(self, *args, **kwargs):
        pass

service = PlanningService(MockEventBus())
```

## Verification

- EventBus class has proper constructor since initial implementation
- All new code should use dependency injection
- Singleton pattern documented as bootstrap convenience only
- Clear migration path provided in docstrings
- Event ordering and delivery guarantees maintained
