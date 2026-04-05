# PKT-PRV-014 — Shared prompt-tag surface contract + sync harness

**Phase:** Phase 4.3  
**Status:** VERIFIED
**Primary owner group:** Providers

## Goal

Implement the shared prompt-tag surface contract, provider config/descriptor additive fields, shared verification matrix, and synchronization discipline.

## Dependencies

- `PKT-PRV-012`
- `PKT-FND-009`
- `PKT-LFC-009`
- `PKT-RLS-010`
- `PKT-JOB-008`
- `PKT-JOB-009`

## Ownership boundary

This packet owns the following documentation and provider-surface delta:

- `docs/specifications/architecture/27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`
- `docs/specifications/architecture/03_Common_Contracts.md`
- `docs/implementation/38_Phase_4_3_Provider_Prompt_Tag_Surface_Integration.md`
- `docs/implementation/providers/10_Prompt_Tag_Surface_Integration_Shared.md`
- `docs/schemas/provider-config.schema.json`
- `docs/schemas/provider-descriptor.schema.json`

## Detailed build steps

1. Confirm all dependencies are verified in `31_Build_Status_and_Work_Registry.md`.
2. Re-read the shared provider prompt-tag surface rules in `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`.
3. Update only the shared surface contract, schema fields, and sync notes for this packet.
4. Add or update the shared prompt-tag surface tests and verification harness.
5. Verify `@plan`, `@implement`, and `@review` normalize to the canonical launch contract.
6. Record recovery / rollback steps for settings drift.

## Acceptance criteria

- this packet's provider surface behavior matches the shared prompt-tag contract
- the provider-specific settings profile is documented
- provider-specific smoke tests exist for the required tags
- no provider-specific tag semantics are introduced

## Recovery procedure

If this packet fails mid-implementation:
- revert provider-specific wrapper or extension changes only
- leave the shared packet untouched unless the shared contract itself is wrong
- disable the provider's `prompt-surface.enabled` flag if needed
- rerun the shared prompt-surface tests plus the provider-specific integration tests

## Notes

adds shared provider prompt-surface fields, descriptor capability fields, fixtures, sync matrix, and common tests
