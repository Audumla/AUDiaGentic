# Phase 4 — Providers and Optional Server Foundation

## Purpose

Add provider execution behind a stable provider contract without changing the earlier lifecycle, release, or job contracts.

## Scope

- provider registry
- provider selection algorithm
- provider health checks
- individual provider adapters
- optional server seam as draft-compatible interface

## Out of scope

- Discord session mirroring
n- replacing in-process execution as the default

## Implementation order

1. PKT-PRV-001 — provider registry and descriptor validation
2. PKT-PRV-002 — provider selection and healthcheck service
3. PKT-PRV-003 through PKT-PRV-009 — provider adapters
4. PKT-SRV-001 — optional server seam draft foundation

## Exit gate

- provider selection is deterministic and testable
- unhealthy provider states fail cleanly without corrupting job records
- the system still works entirely in-process with no server enabled
