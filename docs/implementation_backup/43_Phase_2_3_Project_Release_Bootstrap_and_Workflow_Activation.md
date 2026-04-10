# Phase 2.3 — Project Release Bootstrap and Workflow Activation

## Purpose

Implement the generic project bootstrap path that uses the project’s own release workflow to install or refresh the repository into a current, release-managed state.

## Read before starting

- `docs/specifications/architecture/33_DRAFT_Project_Release_Bootstrap_and_Workflow_Activation.md`
- `docs/specifications/architecture/05_Installation_Update_Cutover_and_Uninstall.md`
- `docs/specifications/architecture/09_Release_Audit_and_Change_Ledger.md`
- `docs/specifications/architecture/10_Release_Please_Baseline_Workflow_Management.md`
- `docs/implementation/04_Phase_2_Release_Audit_Ledger_and_Release_Please.md`
- `docs/implementation/08_Phase_2_Build_Book.md`
- `docs/implementation/31_Build_Status_and_Work_Registry.md`
- `docs/implementation/20_Packet_Dependency_Graph.md`

## Packet scope

- bootstrap command implementation
- installed-state detector adjustment so the bootstrapped repo reports as current
- project scaffold copy/refresh logic for tracked config files
- managed workflow baseline handling
- release summary/audit/check-in regeneration
- integration test coverage for the bootstrap command

## Files in scope

- `src/audiagentic/runtime/release/bootstrap.py`
- `src/audiagentic/channels/cli/main.py`
- `src/audiagentic/runtime/lifecycle/detector.py`
- `tests/integration/release/test_release_bootstrap.py`
- `tests/unit/lifecycle/test_detector.py`
- `docs/implementation/packets/phase-2/PKT-RLS-011.md`

## Acceptance criteria

- a project can be bootstrapped using the generic `release-bootstrap` command
- existing `.audiagentic/providers.yaml` content is preserved
- missing scaffold files are copied from the project scaffold
- the installed-state detector reports `audiagentic-current` after bootstrap
- release docs and workflow artifacts are regenerated deterministically
- tests cover the command end to end

## Recovery considerations

- if bootstrap writes partial files, rerun the command after restoring the sandbox
- if the installed-state detector regresses, restore the legacy marker set only if later phase requirements depend on it
- if the release workflow baseline path changes, update the packet and release docs together rather than forking a separate installer path
- if the managed install baseline grows, keep bootstrap aligned with the shared lifecycle baseline sync seam rather than adding new hard-coded file copy logic here

## Current implementation status

This packet is already implemented and tested in the repository. The document exists to keep the phase/packet trail aligned with the code and to preserve the generic project-level bootstrap behavior.
