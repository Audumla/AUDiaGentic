# PKT-PRV-010 — Job/provider integration seam tests

**Phase:** Phase 4  
**Primary owner group:** Providers

## Goal

Verify that real provider selection and health checks attach to the Phase 3 packet-runner seam without changing Phase 3 job contracts.

## Dependencies

- `PKT-PRV-002`
- `PKT-JOB-003`

## Ownership boundary

Owns:
- `tests/integration/providers/test_job_provider_seam.py`

## Detailed build steps

1. Reuse the Phase 3 packet runner with a real provider selection service.
2. Assert that provider selection occurs outside the packet runner core.
3. Assert that provider health-check failure does not corrupt job state.
4. Assert that Phase 3 fixtures still pass unchanged.

## Acceptance criteria

- packet runner contract remains unchanged from Phase 3
- real provider selection attaches externally
- unhealthy provider path leaves job state consistent
