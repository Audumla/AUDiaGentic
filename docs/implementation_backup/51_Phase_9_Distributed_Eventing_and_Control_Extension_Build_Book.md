# 51 — Phase 9 Federation and Control Extension Build Book

## Goal

Add federation-consumable node event and control contracts while preserving node-local truth.

## Deliverables

- node event types
- node heartbeat persistence
- node federation publisher extension
- optional transport seam
- control request contracts for drain, quarantine, assign, and release

## Allowed early transports

- local event log
- HTTP polling
- WebSocket stream

## Deferred transports

- NATS-backed control/event fabric
- more complex watch/replication fabrics

## Exit gate

Phase 9 is complete when:
- a remote consumer can observe node state safely
- control requests are validated node-side
- no coordinator is required for the node to function
- the federation layer can publish node events without making node-local truth dependent on a coordinator
