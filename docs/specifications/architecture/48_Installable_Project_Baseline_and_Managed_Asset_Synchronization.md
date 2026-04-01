# Installable Project Baseline and Managed Asset Synchronization

Status: implementation-ready spec

## Purpose

Define the installable AUDiaGentic project baseline so a clean or existing project can receive the same managed functionality this repository uses for itself, without copying runtime artifacts or relying on ad hoc manual setup.

This specification freezes the distinction between:
- tracked installable baseline assets
- generated tracked outputs
- runtime-only state

## Why this extension exists

The repository now contains more managed project assets than the original minimal scaffold:
- prompt syntax configuration
- prompt templates and context packs
- provider instruction surfaces
- provider skill assets
- managed workflow files

The lifecycle and release-bootstrap paths must install or refresh those assets deterministically if AUDiaGentic is to behave as an installable template rather than a one-off repository.

## Scope

This extension applies to:
- fresh install into a clean project
- install or refresh into an existing project
- self-host bootstrap of this repository
- deterministic sync of managed tracked assets
- preservation rules for existing project-owned config

## Non-goals

- copying `.audiagentic/runtime/` into target projects
- copying historical runtime job outputs or ledger fragments as install baseline
- treating generated release summaries as install-source artifacts
- introducing a second installer path outside lifecycle/bootstrap flows

## Canonical asset classes

### 1. Managed tracked baseline assets

These are the source assets AUDiaGentic may install or refresh into a project.

#### Project-local baseline
- `.audiagentic/project.yaml`
- `.audiagentic/components.yaml`
- `.audiagentic/providers.yaml`
- `.audiagentic/prompt-syntax.yaml`
- `.audiagentic/prompts/**`

#### Provider instruction baseline
- `AGENTS.md`
- `CLAUDE.md`
- `GEMINI.md`
- `.clinerules/**`
- `.claude/**`
- `.agents/skills/**`

#### Managed workflow baseline
- `.github/workflows/release-please.audiagentic.yml`

### 2. Generated tracked outputs

These are derived from deterministic writers and should be regenerated, not copied as install-source baseline.

- `docs/releases/CURRENT_RELEASE.md`
- `docs/releases/AUDIT_SUMMARY.md`
- `docs/releases/CHECKIN.md`
- `docs/releases/CURRENT_RELEASE_LEDGER.ndjson`

### 3. Runtime-only state

These are not installable baseline assets and must remain runtime-only.

- `.audiagentic/runtime/**`
- per-job logs, launch requests, review bundles, and review reports
- provider stdout/stderr capture files
- ledger fragment working state and sync manifests

## Git and persistence rules

- The repository must not ignore the entire `.audiagentic/` tree.
- Only runtime-only paths under `.audiagentic/runtime/` should be git-ignored by default.
- Installable tracked baseline assets must remain visible to Git so they can define the template applied to other projects.

## Managed sync modes

Each managed asset must declare one of the following behaviors.

### required-managed
AUDiaGentic owns the file content and may refresh it on install/update.

Examples:
- `.audiagentic/prompts/**`
- managed workflow baseline files
- provider rule/skill assets that are treated as shipped baseline

### create-if-missing
AUDiaGentic creates the file when absent but preserves an existing project-owned copy unless an explicit refresh mode is requested.

Examples:
- `.audiagentic/project.yaml`
- `.audiagentic/components.yaml`
- `.audiagentic/providers.yaml`
- `.audiagentic/prompt-syntax.yaml`

### generated-managed
AUDiaGentic regenerates these through deterministic writers rather than copying them from the baseline inventory.

Examples:
- release summary and audit docs
- release ledger views

### runtime-only
Never copied as installable baseline.

Examples:
- `.audiagentic/runtime/**`

## Baseline source of truth

The tracked baseline assets in this repository are the canonical source definition for installation into other projects.

A shared baseline inventory/sync layer must read from that tracked definition and apply it to a target project according to the sync mode rules above.

## Lifecycle requirements

### Fresh install
Fresh install must apply the managed install baseline, not only the minimal scaffold.

### Update and cutover
Update and cutover must preserve project-owned config fields while refreshing managed baseline assets according to sync mode.

### Release bootstrap
Release bootstrap must converge on the same baseline sync engine used by fresh install rather than maintaining a separate hard-coded copy list.

## Provider selection and optional assets

Provider-specific instruction assets may be installed in one of two ways:
- baseline-all: install the full supported-provider instruction set
- baseline-selected: install only the configured provider surfaces plus shared assets

The initial implementation may use baseline-all if that keeps behavior deterministic, but the sync contract must leave a seam for provider-selected installation later.

## Required implementation seam

A shared baseline sync engine must:
1. enumerate the managed baseline inventory
2. classify each asset by sync mode
3. copy or refresh managed assets into the target project
4. preserve existing project-owned config when the contract says preserve
5. never copy runtime-only paths
6. report what was created, refreshed, preserved, or skipped

## Required outputs

The sync engine must produce a machine-readable report containing at least:
- created files
- refreshed files
- preserved files
- skipped files
- runtime-only paths excluded
- warnings

## Dependencies

- `04_Project_Layout_and_Local_State.md`
- `05_Installation_Update_Cutover_and_Uninstall.md`
- `33_DRAFT_Project_Release_Bootstrap_and_Workflow_Activation.md`
- `47_Provider_Prompt_Templates_and_Defaults.md`

## Implementation order

1. `PKT-LFC-011`
2. `PKT-LFC-012`
3. `PKT-LFC-013`

## Notes

This extension is intended to stabilize installation and bootstrap behavior before further provider features expand the managed baseline again.
