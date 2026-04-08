---
id: spec-0018
label: Phase 10 Coordinator Consumption Seam
state: draft
summary: Define coordinator consumption seam
request_refs:
- request-0002
task_refs: []
---

# Phase 10 — Coordinator Consumption Seam

## Purpose

Define the AUDiaGentic-side query/control seam for coordinator or board consumption.

## Scope

- Node listing and node status queries
- Job/session/workspace queries by node
- Delegated job request seam
- Runtime stream and recent-event seam

## Implementation order

1. [PKT-CRD-001](task-0173) — coordinator consumption seam

## Exit gate

- Coordinator seam functional
- Queries work
- Delegation works

# Requirements

1. Coordinator must be able to consume
2. Queries must work
3. Delegation must work

# Constraints

- No core functionality changes

# Acceptance Criteria

1. Coordinator seam functional
2. Queries work
3. Delegation works
