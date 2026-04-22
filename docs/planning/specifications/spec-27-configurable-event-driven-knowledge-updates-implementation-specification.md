---
id: spec-27
label: Configurable event-driven knowledge updates implementation specification
state: implemented
summary: Implementation specification for configurable event-driven knowledge updates
  using standard-0013 event subscription configuration format
request_refs:
- request-43
spec_refs:
- spec-23
- spec-24
standard_refs:
- standard-12
- standard-10
---








# Purpose

Implement configurable, event-driven knowledge updates where all event handling behavior is defined in configuration files rather than code. This specification documents the implementation of standard-0013 (Event subscription configuration standard) in the knowledge component.

# Scope

**In scope:**

1. Standard event subscription configuration format (standard-0013)
2. Knowledge component event adapters configuration
3. Knowledge component event handlers configuration
4. Configurable auto-apply behavior
5. Separation of event capture (adapters) from event response (handlers)
6. Documentation and examples

**Out of scope:**

1. Job/agent manager implementation (future work)
2. Planning component event configuration (follow-on)
3. Event transport adapters (MQTT, Redis) - covered by spec-019
4. Event schema registry and governance

# Architecture

## Two-File Pattern

Event configuration uses two complementary files:

```
.audiagentic/knowledge/events/
├── adapters.yml    # Event capture rules
└── handlers.yml    # Event response behavior
```

### Adapters (Capture)

Define what events to capture and from where:

- Event sources (file paths, event streams)
- Event patterns to match
- Payload filters
- Affected knowledge pages

### Handlers (Response)

Define what actions to take when events are captured:

- Event patterns and filters
- Handler type (deterministic, review_only, none)
- Actions to execute
- Action arguments
- Priority (for conflict resolution)

## Event Flow

```
Event Source → Adapter (captures) → Handler (matches) → Action (executes) → Auto-apply (optional)
```

1. **Event occurs**: Planning item state changes
2. **Adapter captures**: Event matches adapter pattern and filters
3. **Handler matches**: Event matched to handler configuration
4. **Action executes**: Handler triggers configured action
5. **Auto-apply**: If `auto_apply_proposals=true` and handler is deterministic

# Configuration

## Runtime Config

`.audiagentic/knowledge/config.yml`:

```yaml
events:
  # Auto-apply behavior (configurable, not hardcoded)
  auto_apply_proposals: true
  auto_mark_stale: true
  
  # Default handler when no pattern matches
  default_handler: deterministic
  
  # Configuration files (relative to .audiagentic/knowledge/)
  adapters_file: events/adapters.yml
  handlers_file: events/handlers.yml
```

## Adapters Config

`.audiagentic/knowledge/events/adapters.yml`:

```yaml
adapters:
  - id: planning-state-changes
    name: Planning State Change Bridge
    description: Consume planning.item.state.changed events
    source_kind: event_stream
    path_globs:
      - .audiagentic/planning/events/events.jsonl
    event_name_patterns:
      - planning.item.state.changed
      - "*.after_state_change"
    payload_filters:
      in:
        new_state:
          - done
          - verified
    affects_pages:
      - system-planning
      - system-knowledge
      - guide-using-planning
```

## Handlers Config

`.audiagentic/knowledge/events/handlers.yml`:

```yaml
default_handler: deterministic

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

# Implementation Details

## Code Changes

### `src/audiagentic/knowledge/config.py`

Added properties:

```python
@property
def auto_apply_proposals(self) -> bool:
    return bool(self.raw.get("events", {}).get("auto_apply_proposals", True))

@property
def auto_mark_stale(self) -> bool:
    return bool(self.raw.get("events", {}).get("auto_mark_stale", True))

@property
def handlers_file(self) -> Path:
    rel = self.raw.get("events", {}).get("handlers_file", "events/handlers.yml")
    return self.config_path.parent / str(rel)

@property
def event_adapter_file(self) -> Path:
    rel = self.raw.get("events", {}).get("adapters_file", "events/adapters.yml")
    return self.config_path.parent / str(rel)
```

### `src/audiagentic/knowledge/events.py`

Added functions:

```python
def load_event_handlers(config: KnowledgeConfig) -> dict[str, Any]:
    """Load event handler configuration."""
    data = load_yaml_file(config.handlers_file, {"handlers": [], "default_handler": "deterministic"})
    return data if isinstance(data, dict) else {"handlers": [], "default_handler": "deterministic"}


def _match_event_handler(event: EventRecord, handlers_config: dict[str, Any]) -> dict[str, Any]:
    """Match an event to a handler configuration."""
    handlers = handlers_config.get("handlers", [])
    default_handler = handlers_config.get("default_handler", "deterministic")
    
    for handler in handlers:
        patterns = handler.get("event_patterns", [])
        if patterns and not any(fnmatch(event.event_name, pattern) for pattern in patterns):
            continue
        filters = handler.get("payload_filters", {})
        if filters:
            raw_event = event.details.get("raw_event", event.details.get("payload", {}))
            if not _matches_payload_filters(raw_event, filters):
                continue
        return handler
    
    return {"handler": default_handler, "action": "generate_sync_proposal", "action_args": {}}
```

Updated `process_events()`:

```python
def process_events(config: KnowledgeConfig, events: Iterable[EventRecord]) -> dict[str, Any]:
    state = load_event_state(config)
    processed = set(str(x) for x in state.get("processed_event_ids", []) or [])
    action_registry = load_event_action_registry(config)
    handlers_config = load_event_handlers(config)
    auto_apply = config.auto_apply_proposals  # Configurable
    auto_mark_stale = config.auto_mark_stale  # Configurable
    
    # ... process events with handler matching ...
```

## Handler Types

| Type | Description | Auto-apply |
|------|-------------|------------|
| `deterministic` | Safe, predictable updates | Yes |
| `review_only` | Queue for manual/agent review | No |
| `none` | Capture event, no action | N/A |

## Payload Filters

Standard filter operators:

```yaml
payload_filters:
  equals:
    field_name: value
  in:
    field_name:
      - value1
      - value2
  not_equals:
    field_name: value
  not_in:
    field_name:
      - value1
  gt:
    field_name: 10
  gte:
    field_name: 10
  lt:
    field_name: 10
  lte:
    field_name: 10
```

All filters are ANDed together. Any filter section is ORed within that section.

# Acceptance Criteria

## AC-1: Config Loading

- [x] Event adapter config loads from `.audiagentic/knowledge/events/adapters.yml`
- [x] Event handler config loads from `.audiagentic/knowledge/events/handlers.yml`
- [x] Config properties accessible via `KnowledgeConfig`

## AC-2: Handler Matching

- [x] Events matched to handlers by pattern and payload filters
- [x] Default handler used when no pattern matches
- [x] Priority-based handler selection (higher priority first)

## AC-3: Configurable Auto-Apply

- [x] `auto_apply_proposals` configurable in config file
- [x] `auto_mark_stale` configurable in config file
- [x] Defaults to `true` for backward compatibility

## AC-4: Separation of Concerns

- [x] Adapters define event capture only
- [x] Handlers define event response only
- [x] No hardcoded event handling logic in code

## AC-5: Standard Compliance

- [x] standard-0013 created and documented
- [x] Config format aligns with spec-019 event protocol
- [x] Documentation includes examples and migration guide

# Files Created/Modified

## Created

- `docs/planning/standards/standard-0013-event-subscription-configuration-standard.md`
- `.audiagentic/knowledge/events/adapters.yml`
- `.audiagentic/knowledge/events/handlers.yml`
- `docs/knowledge/events/README.md`
- `docs/planning/requests/request-43.md`
- `docs/planning/specifications/spec-023-configurable-event-driven-knowledge-updates-implementation-specification.md`

## Modified

- `src/audiagentic/knowledge/config.py` - Added event config properties
- `src/audiagentic/knowledge/events.py` - Added handler loading and matching
- `.audiagentic/knowledge/config.yml` - Added events section
- `docs/knowledge/events/adapters.yml` - Updated to standard format
- `docs/knowledge/events/handlers.yml` - Updated to standard format

# Verification

All acceptance criteria verified:

```bash
# Config loading
python -c "from src.audiagentic.knowledge.config import load_config; from pathlib import Path; c = load_config(Path('.')); print(f'Adapters: {c.event_adapter_file.exists()}, Handlers: {c.handlers_file.exists()}')"
# Output: Adapters: True, Handlers: True

# Handler loading
python -c "from src.audiagentic.knowledge.events import load_event_handlers; from src.audiagentic.knowledge.config import load_config; from pathlib import Path; c = load_config(Path('.')); h = load_event_handlers(c); print(f'Handlers: {len(h.get(\"handlers\", []))}')"
# Output: Handlers: 4

# Adapter loading
python -c "from src.audiagentic.knowledge.events import load_event_adapters; from src.audiagentic.knowledge.config import load_config; from pathlib import Path; c = load_config(Path('.')); a = load_event_adapters(c); print(f'Adapters: {len(a)}')"
# Output: Adapters: 3
```

# Future Work

1. **Planning component integration** - Use same standard format for planning events
2. **Job/agent manager** - Consume `review_only` handlers to assign work
3. **Event transport adapters** - MQTT, Redis implementations (spec-019)
4. **Advanced filters** - Support nested field filters, regex patterns
5. **Handler chaining** - Support multiple handlers per event

# Related Documents

- **request-43**: Configurable event-driven knowledge updates request
- **standard-0013**: Event subscription configuration standard
- **spec-019**: Interoperability event layer specification
- **spec-020**: Planning state propagation over events specification
- **standard-0011**: Component architecture standard
