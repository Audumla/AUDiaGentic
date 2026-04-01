# Node Execution and Federation Extension

## Purpose

Define an additive node model for multi-instance execution without changing single-node correctness.

## Scope

This extension covers:
- node identity
- node descriptor contracts
- node heartbeat and status
- node-local job ownership fields
- node-local runtime persistence

## Deliverables

- node descriptor contract
- node heartbeat contract
- node runtime helpers
- node status surface
- additive ownership fields for node-local jobs

## Non-goals

- no discovery provider is required
- no coordinator UI is introduced
- no baseline single-node behavior is changed

## Design rule

Node-local truth stays authoritative. Federation is additive and must not make the node dependent on remote control to function.
