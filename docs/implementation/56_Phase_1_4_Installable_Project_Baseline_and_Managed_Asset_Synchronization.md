# Phase 1.4 — Installable Project Baseline and Managed Asset Synchronization

## Purpose

Bring the lifecycle and bootstrap model back into alignment with the repository's real managed baseline so AUDiaGentic can be installed into a clean or existing project as a template, not just evolved in-place inside this repository.

## Read before starting

- `docs/specifications/architecture/49_Repository_Domain_Refactor_and_Package_Realignment.md`
- `docs/implementation/57_Phase_0_3_Repository_Domain_Refactor_and_Package_Realignment.md`
- `docs/specifications/architecture/04_Project_Layout_and_Local_State.md`
- `docs/specifications/architecture/05_Installation_Update_Cutover_and_Uninstall.md`
- `docs/specifications/architecture/33_DRAFT_Project_Release_Bootstrap_and_Workflow_Activation.md`
- `docs/specifications/architecture/48_Installable_Project_Baseline_and_Managed_Asset_Synchronization.md`
- `docs/implementation/03_Phase_1_Lifecycle_and_Project_Enablement.md`
- `docs/implementation/07_Phase_1_Build_Book.md`
- `docs/implementation/31_Build_Status_and_Work_Registry.md`

## Packet scope

- canonical baseline asset inventory
- managed sync-mode classification
- shared baseline sync engine for lifecycle/bootstrap
- convergence of fresh-install and release-bootstrap on the same sync logic
- tests covering clean-project and existing-project install behavior

## Files expected to be in scope during implementation

- `src/audiagentic/lifecycle/baseline_sync.py`
- `src/audiagentic/lifecycle/fresh_install.py`
- `src/audiagentic/release/bootstrap.py`
- `tools/seed_example_project.py`
- `tests/e2e/lifecycle/test_fresh_install.py`
- `tests/integration/release/test_release_bootstrap.py`
- `tests/integration/test_example_scaffold.py`
- `docs/examples/project-scaffold/`
- selected provider instruction assets and prompt templates used as the managed baseline source

## Acceptance criteria

- installable tracked baseline assets are explicitly defined and classified
- runtime-only state is excluded from the install baseline
- fresh install and release bootstrap use the same shared baseline sync seam
- prompt syntax, prompt templates, and managed provider instruction assets are included in the install baseline contract
- clean-project and existing-project behavior are both covered by tests
- this repository remains usable as a self-hosting validation target without becoming a special-case installer

## Packet execution order

1. `PKT-LFC-011` freezes the inventory and sync-mode classification
2. `PKT-FND-010` through `PKT-FND-013` complete the repository domain refactor checkpoint before additional baseline-sync implementation resumes
3. `PKT-LFC-012` implements the shared sync engine
4. `PKT-LFC-013` converges fresh-install and release-bootstrap on that engine

## Recovery considerations

- if the baseline inventory changes, update the asset classification and install tests together
- if provider instruction assets diverge by provider, keep that expressed as inventory/config and not as an ad hoc copy list in lifecycle code
- if the repo carries extra experimental local files, do not silently promote them into the installable baseline without updating the baseline inventory contract first
