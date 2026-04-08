---
id: spec-0012
label: Phase 4 Providers and Optional Server Foundation
state: draft
summary: Add providers and optional server seam
request_refs:
- request-0002
task_refs: []
---

# Phase 4 — Providers and Optional Server Seam

## Purpose

Add providers and an optional extraction boundary without changing earlier cores.

## Scope

- Provider registry
- Health checks
- Deterministic provider selection
- Provider adapters
- Optional service seam that can be ignored by default

## Out of scope

- Discord delivery
- complex provider logic

## Implementation order

1. [PKT-PRV-001](task-0078) — provider registry
2. [PKT-PRV-002](task-0079) — health checks
3. [PKT-PRV-003](task-0080) — provider selection
4. [PKT-PRV-004](task-0081) — provider adapters
5. [PKT-PRV-005](task-0082) — service seam
6. [PKT-PRV-006](task-0083) through [PKT-PRV-078](task-0156) — provider-specific implementations

## Exit gate

- all providers functional
- health checks pass
- selection deterministic
- service seam optional

# Requirements

1. Providers must be pluggable
2. Health checks must work
3. Selection must be deterministic

# Constraints

- No Discord delivery
- No complex provider logic

# Acceptance Criteria

1. All providers functional
2. Health checks pass
3. Selection deterministic
4. Service seam optional
