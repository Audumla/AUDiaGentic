---
id: task-254
label: Create interoperability package structure with transport protocol abstraction
state: done
summary: 'Scaffold src/audiagentic/interoperability/ package: protocol.py (EventBusProtocol,
  SubscriptionHandle, DeliveryMode), envelope.py, exceptions.py, config.py, adapters/__init__.py,
  and __init__.py with init_bus()/get_bus() factory — no singleton'
spec_ref: spec-23
request_refs:
- request-17
standard_refs:
- standard-5
- standard-6
---














# Description

Scaffold the `src/audiagentic/interoperability/` package structure and bootstrap wiring for the event layer. This task creates the foundational package layout, EventBus singleton/service registration, and component subscriber auto-discovery mechanism.

**Files to create:**
- `src/audiagentic/interoperability/__init__.py` - Package exports, EventBus singleton (convenience)
- `src/audiagentic/interoperability/bus.py` - EventBus class with explicit injection (preferred) + singleton (convenience)
- `src/audiagentic/interoperability/store.py` - EventStore interface placeholder
- `src/audiagentic/interoperability/replay.py` - ReplayService placeholder
- `src/audiagentic/interoperability/envelope.py` - EventEnvelope dataclass
- `src/audiagentic/interoperability/exceptions.py` - Custom exceptions
- `.audiagentic/interoperability/config.yaml` - Default configuration

**Bootstrap wiring:**
- EventBus singleton registration in `src/audiagentic/__init__.py`
- Component subscriber auto-discovery mechanism
- Startup sequence: bus initializes before components
- **Transport abstraction:** Define EventBusProtocol interface for future MQ migration

**MQ Migration Simplicity:**
- EventBusProtocol defines abstract interface (publish, subscribe, unsubscribe)
- InProcessEventBus implements protocol
- Future: ExternalMQBus implements same protocol
- Components depend on protocol, not concrete implementation

# Acceptance Criteria

- Package structure created at `src/audiagentic/interoperability/`
- EventBus singleton accessible via `from audiagentic.interoperability import EventBus`
- Default configuration file exists at `.audiagentic/interoperability/config.yaml`
- Bootstrap wiring allows components to register subscribers at startup
- Package imports cleanly without circular dependencies
- Smoke test proves `import audiagentic.interoperability` succeeds

# Notes

This task is scaffolding only. No functional implementation beyond package structure and bootstrap wiring.
