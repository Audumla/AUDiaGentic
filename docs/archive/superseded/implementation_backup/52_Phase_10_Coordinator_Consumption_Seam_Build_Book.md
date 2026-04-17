# 52 — Phase 10 Coordinator Consumption Seam Build Book

## Goal

Define the AUDiaGentic-side federation consumption seam that an external coordinator or board may consume.

## Scope

This phase does not build the coordinator UI.
It builds only the backend query/control seam that consumes the federation layer.

## Deliverables

- list nodes
- get node status
- list local jobs by node
- query assignable capabilities
- submit delegated job request
- request node control operations
- request runtime streams or recent events

## Exit gate

Phase 10 is complete when:
- a non-UI consumer can coordinate multiple nodes using only stable AUDiaGentic contracts
- the same AUDiaGentic node still works without any coordinator attached
