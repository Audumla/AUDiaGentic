# PKT-PRV-013 — Provider CLI/status inspection

**Phase:** Phase 4.2  
**Status:** VERIFIED
**Primary owner group:** Providers

## Goal

Add a terminal status command that inspects provider configuration, CLI availability, and model-catalog presence so maintainers can verify the provider surface without opening each CLI by hand.

## Why this packet exists now

The project now supports multiple local provider CLIs and runtime model catalogs. We need one deterministic status view that reports whether each provider is configured, whether its CLI can be executed from the terminal, and whether a model catalog exists for that provider.

## Dependencies

- `PKT-PRV-012`

## Concrete provider status inputs

This packet must report the following data points:

- provider config `enabled`
- provider config `install-mode`
- provider config `access-mode`
- provider config `default-model`
- provider config `model-aliases`
- CLI availability for `access-mode: cli`
- runtime catalog path
- runtime catalog presence
- runtime catalog model count when present

## Ownership boundary

This packet owns the following implementation surface:

- `src/audiagentic/execution/providers/status.py`
- `src/audiagentic/channels/cli/main.py`
- `tools/provider_status.py`
- `tests/unit/providers/test_provider_status.py`
- `tests/integration/providers/test_provider_status_cli.py`
- `docs/implementation/31_Build_Status_and_Work_Registry.md`
- `docs/Implementation_tracker.md`

### It may read from
- provider config in `.audiagentic/providers.yaml`
- runtime catalogs under `.audiagentic/runtime/providers/<provider-id>/model-catalog.json`
- provider CLI help/version output

### It must not edit directly
- catalog or provider schema files unless a dependency explicitly requires it
- model selection logic in `src/audiagentic/execution/providers/models.py`
- release-ledger files

## Public contracts used

- provider config contract in `03_Common_Contracts.md`
- provider model catalog contract in `24_DRAFT_Provider_Model_Catalog_and_Selection.md`
- provider status behavior in `providers-status` CLI output

## Detailed build steps

1. Add provider config loading and validation for the status command.
2. Probe CLI-backed providers through the terminal and capture basic availability output.
3. Read runtime model catalogs and report catalog presence and model count.
4. Wire the status command into the main CLI entrypoint.
5. Add unit and integration tests for config-missing and live-provider cases.
6. Update the build registry and implementation tracker with the new packet.

## Integration points

- `src/audiagentic/config/provider_catalog.py`
- `src/audiagentic/execution/providers/health.py`
- `src/audiagentic/execution/providers/models.py`
- `src/audiagentic/channels/cli/main.py`
- `tools/provider_status.py`
- `tests/integration/providers/test_provider_status_cli.py`

## Acceptance criteria

- terminal command reports provider config health for all configured providers
- CLI-backed providers are probed through the terminal and their availability is reported
- runtime catalogs are surfaced when present without requiring network access
- missing provider config returns an error envelope
- docs and registry show the packet as verified after tests pass

## Recovery procedure

If this packet fails mid-implementation:
- revert changes in `src/audiagentic/execution/providers/status.py`, `src/audiagentic/channels/cli/main.py`, and `tools/provider_status.py`
- remove the new provider-status tests
- restore the registry and tracker rows if they were partially updated
- rerun the focused provider-status test set before retrying

## Out of scope

- starting interactive provider sessions
- querying remote provider APIs for live model lists
- automatic catalog refresh
