---
id: request-18
label: Automatic state propagation for planning hierarchies
state: closed
summary: Implement automatic state transitions that propagate up planning hierarchies
  using interoperability layer events
source: follow-up to request-35
guidance: standard
current_understanding: 'Building on request-35 (event mechanism), need automatic
  state propagation rules: WP→in_progress when any task→in_progress, WP→done when
  all tasks→done, Plan→in_progress when any WP→in_progress, Plan→done when all WPs→done,
  Spec→in_progress when any plan→in_progress, Spec→done when all plans→done. Rules
  should be configurable per workflow and respect blocking states (e.g., can''t go
  to done if any child is blocked). Need to handle edge cases: manual state overrides,
  conflicting transitions, and state rollback scenarios. '
open_questions:
- Should state propagation be immediate or batched?
- How to handle manual state overrides vs automatic propagation?
- What happens on state rollback (e.g., task done→ready)?
- Should propagation rules be workflow-specific or global?
meta:
  request_type: enhancement
standard_refs:
- standard-1
spec_refs:
- spec-20
---







# Understanding

This request builds on `request-17`. Once a shared event/interoperability layer exists, planning item states should propagate through the hierarchy automatically instead of relying on manual parent updates. The need is clear at the task, work package, plan, and specification levels, but the exact propagation contract belongs in the linked spec rather than in the request itself.

# Open Questions

No open questions remain at the request level. The remaining rule and contract details belong in [spec-020](../specifications/spec-020-planning-state-propagation-over-events-specification.md).

# Problem

Even when child items progress correctly, parent items can remain stale until someone updates them manually. That creates avoidable maintenance work, inconsistent dashboards, and unreliable workflow signals for both humans and agents. Without automatic propagation, state stops being a trustworthy indicator of what is actually ready, blocked, in progress, or complete.

# Desired Outcome

Add automatic, event-driven state propagation through the planning hierarchy so parent items stay aligned with meaningful child-state changes. The behavior should support configurable defaults, workflow-specific overrides, conflict handling, rollback-safe behavior, and continued manual control where needed. The exact propagation rules, metadata behavior, and configuration contract are defined in `spec-020`.

# Constraints

- This request depends on the interoperability event layer from `request-17` / `spec-019`.
- Existing workflow/state-machine definitions must remain authoritative.
- Manual state changes must remain supported.
- Propagation must be disableable for debugging and controlled rollout.
- The work must not retroactively rewrite existing planning records.

# Non-Goals

- Implementing the interoperability layer itself.
- Redefining the planning workflow/state model.
- Retrofitting historical records to match new propagation rules.

# Compatibility

- Existing manual `api.state()` usage should continue to work.
- Existing hooks/automations should remain compatible during rollout.
- Default behavior should remain predictable even when no explicit propagation config is present.

# Verification Expectations

- A meaningful child-state change updates the appropriate parent item automatically.
- Propagation behaves correctly across task -> wp -> plan -> spec relationships.
- Conflict resolution and rollback behavior are observable and testable.
- Manual overrides remain possible without making automatic propagation unsafe or opaque.

# Notes
This request is intentionally narrower than the underlying event-layer work. It depends on the event foundation from `request-17`, and its detailed rule set is owned by `spec-020`.

Assessment on 2026-04-17: request remains valid and still open. Core propagation exists and planning now subscribes to `planning.item.state.changed`, but remaining work still includes knowledge-side integration hardening (`task-0254`, `task-0261`) and propagation audit/repair tooling (`task-0265`). Non-core deferred items were cancelled during this review.

Isolation update on 2026-04-17: created `task-0006` to track an observed propagation defect where automatic parent updates attempted workflow-invalid transitions such as `draft -> done` during child-driven cascades. This is now part of the remaining request scope alongside audit/repair tooling and knowledge-handler follow-up.

Completion update on 2026-04-17: the remaining request-specific follow-ups are now implemented. `task-0006` fixed invalid automatic parent transitions, `task-0265` added audit/repair CLI coverage, and the remaining cross-component knowledge reaction path now executes correctly via the runtime planning event handler work completed alongside this request review. Shared interoperability documentation/plan items may remain active for request-17 bookkeeping, but the request-18 scope itself is complete.
