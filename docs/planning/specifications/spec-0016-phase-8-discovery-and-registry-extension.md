---
id: spec-0016
label: Phase 8 Discovery and Registry Extension
state: draft
summary: Add pluggable node discovery and registration
request_refs:
- request-0002
task_refs: []
---

# Phase 8 — Discovery and Registry Extension

## Purpose

Add pluggable node discovery and registration.

## Scope

- Locator provider contract
- Static registry provider
- Optional zeroconf provider seam
- Optional external registry provider seam

## Implementation order

1. PKT-DIS-001 — locator provider contract
2. PKT-DIS-002 — static registry provider
3. PKT-DIS-003 — optional provider seams

## Exit gate

- Discovery functional
- Registration works
- Pluggable

# Requirements

1. Discovery must be pluggable
2. Registration must work
3. Must be optional

# Constraints

- No baseline dependency

# Acceptance Criteria

1. Discovery functional
2. Registration works
3. Pluggable
