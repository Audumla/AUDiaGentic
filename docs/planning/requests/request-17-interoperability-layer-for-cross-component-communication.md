---
id: request-17
label: Interoperability layer for cross-component communication
state: closed
summary: Create lightweight interoperability layer as foundation component for cross-component
  events, state propagation, and reactive workflows
source: user feedback on state management gaps
guidance: standard
current_understanding: 'Current state management is manual: tasks can be marked done
  while their parent work packages remain in draft/ready state. The hook system (before_create,
  after_update, etc.) is action-oriented but doesn''t support reactive state transitions.
  Need event-driven architecture where state changes emit events that can trigger
  automatic state propagation up the hierarchy.'
open_questions: []
meta:
  request_type: enhancement
standard_refs:
- standard-1
spec_refs:
- spec-23
---










# Understanding

State management across planning records is still largely manual. Child-item state changes do not automatically inform parent items, and the current hook model is action-oriented rather than event-oriented. We need a shared interoperability layer so components can announce post-commit facts and react to them without direct coupling.

# Open Questions
No open questions remain at the request level. All design decisions are captured in [spec-019](../specifications/spec-019-interoperability-event-layer-specification.md).
# Problem

The system has no shared mechanism for cross-component communication after a state change has already been committed. When a task transitions to `done`, nothing informs its parent work package or any other interested subsystem. That gap forces manual state maintenance, encourages point-to-point integrations, and makes reactive workflows difficult to add safely.

# Desired Outcome

Introduce a lightweight interoperability event layer that lets components publish and subscribe to post-commit facts with minimal integration overhead. The layer should support decoupled workflows, optional persistence/replay, and future cross-component automation without requiring external infrastructure for core operation.

**Observable outcome:** Components can publish events and have subscribers react without direct imports between peers. State changes in one component (e.g., planning task done) trigger actions in another (e.g., knowledge page marked stale) through the event layer. The layer supports SYNC (blocking) and ASYNC (background) modes, optional file persistence, replay for recovery, and cycle detection via propagation depth limits.

# Constraints

- Core operation must remain dependency-light and work without an external message broker.
- The solution must avoid circular dependencies and keep bootstrap wiring explicit.
- Events must represent facts announced after a successful state change, not commands that own the change.
- Existing components should require only limited integration changes rather than deep rewrites.
- Python 3.10+ compatibility must be preserved.

# Non-Goals

- Replacing the existing hook system outright.
- Solving planning-specific propagation rules in this request.
- Adding distributed delivery guarantees or external transport adapters in V1.

# Compatibility

- Existing `planning/events.jsonl` emission can remain during transition.
- Existing hook wiring remains additive and should not break because of this layer.
- Downstream adapters may migrate incrementally to canonical events once the layer exists.

# Verification Expectations

- Components can publish and subscribe without direct imports between peers.
- Subscriber failures are isolated and do not break event delivery to other subscribers.
- Optional persistence/replay works when enabled and stays non-blocking for the core publish path.
- The resulting layer is sufficient to support planning-state propagation as follow-on work.

# Notes

This request is the foundation request. Automatic planning-state propagation is tracked separately in `request-18` and specified in `spec-020`.
