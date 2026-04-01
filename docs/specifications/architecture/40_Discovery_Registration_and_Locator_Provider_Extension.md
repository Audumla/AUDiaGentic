# Discovery Registration and Locator Provider Extension

## Purpose

Add pluggable discovery and registration providers without making discovery a baseline dependency.

## Scope

This extension defines:
- a locator provider contract
- a static registry provider
- optional operator-configurable registry selection
- an optional zeroconf provider
- an optional external registry provider seam

## Deliverables

- locator provider contract
- static registry backend
- registry selection rules
- optional discovery backends

## Non-goals

- no discovery backend is mandatory
- no coordinator UI is required
- local-only operation must remain valid when discovery is disabled
