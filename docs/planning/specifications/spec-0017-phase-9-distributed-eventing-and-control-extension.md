---
id: spec-0017
label: Phase 9 Distributed Eventing and Control Extension
state: draft
summary: Add federation-consumable event and control request validation
request_refs:
- request-0002
task_refs: []
---

# Phase 9 — Distributed Eventing and Control Extension

## Purpose

Add federation-consumable event and node-side control request validation.

## Scope

- Node event families
- Heartbeat/status publication
- Control request contracts
- Optional stream transport seam

## Implementation order

1. PKT-EVT-001 — node event families
2. PKT-EVT-002 — control request contracts

## Exit gate

- Eventing functional
- Control validated
- Federation works

# Requirements

1. Events must be federation-consumable
2. Control requests must be validated
3. Node-local truth preserved

# Constraints

- No single-node correctness changes

# Acceptance Criteria

1. Eventing functional
2. Control validated
3. Federation works
