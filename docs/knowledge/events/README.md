# Knowledge Event Configuration

This directory contains documentation for event-driven knowledge updates. The actual configuration files are in `.audiagentic/knowledge/events/`.

Configuration aligns with **standard-0013** (Event subscription configuration standard) and **spec-0055** (Interoperability event layer specification).

## Files

### Runtime Configuration (in `.audiagentic/knowledge/events/`)

- **adapters.yml**: Defines event capture rules (what events to listen for)
- **handlers.yml**: Defines event response behavior (what actions to take)

### Documentation (in `docs/knowledge/events/`)

- **README.md**: This file (documentation)

## Architecture

Event handling follows a two-file pattern for separation of concerns:

```
Event Source → Adapter (captures) → Handler (responds) → Action (executes)
```

### Adapters

Adapters define:
- Event sources (file paths, event streams)
- Event patterns to match
- Payload filters
- Affected knowledge pages

### Handlers

Handlers define:
- Event patterns and filters
- Handler type (deterministic, review_only, none)
- Actions to execute
- Action arguments
- Priority (for conflict resolution)

## Configuration

Event behavior is controlled via `.audiagentic/knowledge/config.yml`:

```yaml
events:
  auto_apply_proposals: true    # Auto-apply deterministic proposals
  auto_mark_stale: true         # Auto-mark pages stale
  default_handler: deterministic # Default when no pattern matches
  adapters_file: events/adapters.yml   # Relative to .audiagentic/knowledge/
  handlers_file: events/handlers.yml   # Relative to .audiagentic/knowledge/
```

Config files are located in `.audiagentic/knowledge/events/` (runtime config directory).

## Handler Types

| Type | Description | Auto-apply |
|------|-------------|------------|
| `deterministic` | Safe, predictable updates | Yes |
| `review_only` | Queue for manual/agent review | No |
| `none` | Capture event, no action | N/A |

## Event Flow

1. **Event occurs**: Planning item state changes
2. **Adapter captures**: Event matches adapter pattern
3. **Handler matches**: Event matched to handler config
4. **Action executes**: Handler triggers configured action
5. **Auto-apply**: If `auto_apply_proposals=true` and handler is deterministic

## Example: Planning State Change

When a planning task transitions to `done`:

1. Event emitted: `planning.item.state.changed`
2. Adapter `planning-state-changes` captures it (matches pattern + filter)
3. Handler matches (pattern: `planning.item.state.changed`, filter: `new_state in [done, verified]`)
4. Action `mark_stale_and_generate_sync_proposal` executes
5. Affected pages marked stale, sync proposals generated
6. Proposals auto-applied (deterministic handler + `auto_apply_proposals=true`)

## Standard Format

See **standard-0013** for the complete event subscription configuration standard, including:
- Field definitions
- Payload filter operators
- Pattern matching rules
- Component-specific extensions
- Migration guides

## Future Work

- Job/agent manager will consume `review_only` handlers to assign work
- Planning component will use the same standard format
- Event transport adapters (MQTT, Redis) will use the same config format

## Related Documents

- standard-0013: Event subscription configuration standard
- spec-0055: Interoperability event layer specification
- spec-0056: Planning state propagation over events specification
- `.audiagentic/knowledge/config.yml`: Runtime configuration
- `.audiagentic/knowledge/events/adapters.yml`: Event adapter configuration
- `.audiagentic/knowledge/events/handlers.yml`: Event handler configuration
- `src/audiagentic/knowledge/events.py`: Implementation
