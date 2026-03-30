# PKT-PRV-020 — cline prompt-tag surface integration

**Phase:** Phase 4.3  
**Primary owner group:** Providers

## Goal

Implement the cline CLI / VS Code prompt-tag rollout.

## Dependencies

- `PKT-PRV-009`
- `PKT-PRV-014`

## Ownership boundary

This packet owns the following documentation and provider-surface delta:

- `docs/implementation/providers/07_Cline_Plan.md`

## Detailed build steps

1. Confirm all dependencies are verified in `31_Build_Status_and_Work_Registry.md`.
2. Re-read the shared provider prompt-tag surface rules in `27_Provider_Prompt_Tag_Recognition_and_Surface_Synchronization.md`.
3. Update only the provider-specific surface mode, settings profile, and adapter notes for this packet.
4. Add or update provider-specific prompt-tag smoke tests.
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

cline settings-profile, wrapper/extension entry points, and smoke tests
