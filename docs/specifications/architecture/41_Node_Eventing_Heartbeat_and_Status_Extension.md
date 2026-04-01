# Node Eventing Heartbeat and Status Extension

## Purpose

Add node-level eventing, heartbeat persistence, and control contracts while preserving node-local truth.

## Scope

This extension covers:
- node event families
- heartbeat persistence
- node status records
- node-side control request validation
- additive stream or polling transport seams

## Deliverables

- node event record types
- heartbeat persistence rules
- node status publication rules
- control request contract families

## Non-goals

- no control consumer may bypass node-side ownership checks
- no coordinator is required for a node to keep working
