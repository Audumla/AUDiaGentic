# PKT-LFC-011 — Installable baseline inventory and sync-mode classification

**Phase:** Phase 1.4  
**Status:** READY_FOR_REVIEW  
**Owner:** Lifecycle  
**Scope:** workspace

## Goal

Freeze the installable AUDiaGentic project baseline so lifecycle and bootstrap behavior know exactly which tracked assets are install-source material, which are generated, and which are runtime-only.

## Dependencies

- Phase 1 VERIFIED
- Phase 2.3 VERIFIED

## Owns

- `docs/specifications/architecture/48_Installable_Project_Baseline_and_Managed_Asset_Synchronization.md`
- `docs/specifications/architecture/04_Project_Layout_and_Local_State.md`
- `docs/specifications/architecture/05_Installation_Update_Cutover_and_Uninstall.md`
- `docs/implementation/03_Phase_1_Lifecycle_and_Project_Enablement.md`
- `docs/implementation/07_Phase_1_Build_Book.md`
- `docs/implementation/11_Executable_Packets_Lifecycle.md`

## Must define

- canonical installable asset inventory
- sync modes for each asset class
- explicit exclusion of `.audiagentic/runtime/**`
- source-of-truth rule that this repo's tracked baseline defines install content

## Acceptance criteria

- there is one canonical install-baseline taxonomy
- lifecycle docs and local-state docs agree on tracked vs generated vs runtime-only assets
- provider instruction assets and prompt templates are explicitly accounted for

## Implementation result

This packet now freezes:
- the canonical asset-class taxonomy
- the current baseline inventory table
- the sync-mode definitions for tracked baseline, generated outputs, and runtime-only state
- the rule that the repository's tracked baseline, not only the example scaffold, defines what is installable
