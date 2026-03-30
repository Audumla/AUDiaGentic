# PKT-RLS-011 — Project Release Bootstrap and Workflow Activation

**Phase:** Phase 2.3  
**Status:** VERIFIED  
**Owner:** Codex  
**Scope:** project release bootstrap and workflow activation using the project’s own release machinery  

## Goal

Provide a generic bootstrap path that installs or refreshes the project into a release-managed current state without introducing a special self-host-only script.

## Dependencies

- Phase 1 verified
- PKT-LFC-003 verified
- PKT-RLS-006 verified
- PKT-RLS-008 verified

## Implementation summary

The bootstrap command:

- creates `.audiagentic/project.yaml`, `.audiagentic/components.yaml`, and `.audiagentic/installed.json` from the scaffold if they are missing
- preserves an existing `.audiagentic/providers.yaml`
- ensures the Release Please managed workflow baseline exists
- syncs the current release ledger
- regenerates the current release markdown
- regenerates audit and check-in summaries
- reports the bootstrapped project as `audiagentic-current`

## Files

### Code

- `src/audiagentic/release/bootstrap.py`
- `src/audiagentic/cli/main.py`
- `src/audiagentic/lifecycle/detector.py`

### Tests

- `tests/integration/release/test_release_bootstrap.py`
- `tests/unit/lifecycle/test_detector.py`

### Docs

- `docs/specifications/architecture/33_DRAFT_Project_Release_Bootstrap_and_Workflow_Activation.md`
- `docs/implementation/43_Phase_2_3_Project_Release_Bootstrap_and_Workflow_Activation.md`
- `docs/specifications/architecture/05_Installation_Update_Cutover_and_Uninstall.md`

## Acceptance criteria

- bootstrap runs successfully from the CLI
- bootstrap on a project root produces the expected release artifacts
- bootstrap does not overwrite an existing providers configuration
- the installed-state detector reports the project as current after bootstrap

## Test evidence

- targeted lifecycle/bootstrap tests passed
- command-level bootstrap run against the repository root completed successfully

## Notes

This packet is intentionally generic and should remain part of the project’s normal release machinery. It is not a one-off self-host installer and should not be split into a special-purpose script.
