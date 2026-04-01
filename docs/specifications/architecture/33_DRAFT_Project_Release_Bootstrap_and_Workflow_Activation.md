# DRAFT — Project Release Bootstrap and Workflow Activation

## Purpose

Define how AUDiaGentic can bootstrap a project into its own release workflow using the project’s own release machinery rather than any one-off self-host script.

This extension treats the repository itself as the test target and the activation target.

## Scope

- project-local release bootstrap entry point
- deterministic installation state creation or refresh
- managed Release Please workflow/config activation
- preservation of existing tracked provider and lifecycle config
- regeneration of current release, audit, and check-in docs after bootstrap
- repository-local verification that the project reports itself as current when bootstrapped

## Non-goals

- special self-host-only scripts
- alternate installation paths that bypass the release core
- ad hoc workflow generation outside the release subsystem
- changing the meaning of earlier install/update/cutover phases

## Contract expectations

The bootstrap flow must:

1. inspect the installed state
2. create or refresh `.audiagentic/project.yaml`, `.audiagentic/components.yaml`, and `.audiagentic/installed.json` from the project scaffold when missing
3. preserve existing provider configuration
4. prepare or validate the managed Release Please workflow/config baseline
5. regenerate release views using the same release subsystem used for normal project operation
6. leave the project in a state that reports as current through the installed-state detector

The bootstrap flow must converge on the same managed baseline sync rules used by lifecycle
install/update flows rather than preserving a separate hard-coded scaffold copy list.

## Required outputs

- `.audiagentic/installed.json`
- `.github/workflows/release-please.audiagentic.yml`
- refreshed `docs/releases/AUDIT_SUMMARY.md`
- refreshed `docs/releases/CHECKIN.md`
- refreshed `docs/releases/CURRENT_RELEASE.md`
- refreshed `docs/releases/CURRENT_RELEASE_LEDGER.ndjson`

## Dependencies

- Phase 1 lifecycle state detection and manifest handling
- Phase 2 release fragment, sync, summary, audit, and Release Please management
- release ledger generation and current-release regeneration rules

## Implementation order

1. `PKT-RLS-011`

## Notes

This capability is intentionally generic. It should remain usable as a project bootstrapping primitive even when the repository is not treated as a special self-host case.
