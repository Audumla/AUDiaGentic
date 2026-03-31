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
- replacing in-process execution as the default

## Implementation order

1. PKT-PRV-001 — provider registry and descriptor validation
2. PKT-PRV-002 — provider selection and healthcheck service
3. PKT-PRV-003 through PKT-PRV-009 — provider adapters
4. PKT-PRV-011 — provider access-mode contract + health config rules
5. PKT-SRV-001 — optional server seam draft foundation

## Exit gate

- provider selection is deterministic and testable
- unhealthy provider states fail cleanly without corrupting job records
- the system still works entirely in-process with no server enabled

## Follow-on phases

Provider model catalog and selection extensions are defined in Phase 4.1.
See `11_Phase_4_1_Provider_Model_Catalog_and_Selection.md`.

Provider status/validation behavior is defined in Phase 4.2.
Prompt-tag surface recognition and synchronization are defined in Phase 4.3.
Provider execution compliance and isolated per-provider implementation docs are defined in Phase 4.4.
Provider prompt-trigger launch behavior is drafted in Phase 4.6.
Provider availability and auto-install orchestration is drafted in Phase 4.7.
Provider live stream and progress capture are drafted in Phase 4.9.
Provider live input and interactive session control is in progress in Phase 4.10.
