# Approval Core and Event Model

## Approval core

The approval service is transport-neutral. Discord and any future UI act as adapters.

## Approval rules

- one pending approval per `(project-id, kind, source-id)` tuple
- requesting a duplicate pending approval for the same tuple must return the existing approval id
- pending approvals expire after default TTL unless caller overrides
- expired approvals move blocked jobs/releases into a recoverable paused state
- approvals may be cancelled by lifecycle or operator action before resolution

## Approval transport model

Approval adapters consume and emit through the core service:
- request approval
- poll/list pending approvals
- resolve approval
- cancel approval

## Event publisher contract

Discord and any future UI/server seam consume events through a transport-neutral publisher contract:

```python
publish(event_envelope) -> None
subscribe(filter_spec) -> subscription_handle
unsubscribe(subscription_handle) -> None
```

Delivery guarantees in MVP:
- publish is best-effort append plus local dispatch
- local file persistence is attempted before adapter dispatch
- subscribers may filter by `project-id`, `event-type`, or `source-kind`
- event delivery is at-least-once within one process; consumers must tolerate duplicates by `event-id`

## Event persistence

MVP stores events in `.audiagentic/runtime/logs/events.ndjson`

Retention policy in MVP:
- retain current file until it reaches 10 MB
- rotate to `events.<timestamp>.ndjson`
- keep last 10 rotated files

Ordering rule:
- local append order is authoritative for one process
- consumers must sort by `occurred-at` and then `event-id` if they need deterministic replay


Retention and rotation clarifications:
- active `events.ndjson` rotates at 10 MB
- last 10 rotated files are retained
- no time-based archival is required in MVP
- correlation and trace ids are deferred until a later server phase


## Event publishing in MVP

The core event model uses a project-local append-only log as the publication mechanism. `EventPublisher.publish()` is best-effort and writes JSON events to `.audiagentic/runtime/logs/events.ndjson`.

MVP rules:
- no required external message broker
- overlays such as Discord consume by tailing/filtering project-local events
- failure to publish an event must never mutate approval state retroactively
- event rotation is local-log based; archival/export is a DRAFT future enhancement


## Phase 3.2 additive review gating note

Structured review does not replace the approval core. A `ReviewBundle` may satisfy a workflow's review requirement, but any later explicit approval step still flows through the approval service. Review evidence and approval state must remain separate contracts.
