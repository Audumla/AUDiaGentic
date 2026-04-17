---
id: task-0172
label: Scope manifest and migration-registry scaffolding
state: done
summary: Define manifest and migration-registry scaffolding without drifting into
  installer implementation
spec_ref: spec-005
---








# Description

Review the manifest and migration-registry proposal and keep it narrowly scoped as planning/config scaffolding for future installation and upgrade flows.

**Status: IMPLEMENTED**

All implementation work for task-0172 is complete:
- Task scoped as documentation and scope control only (no runtime behavior)
- Cross-references existing lifecycle architecture docs (05_Installation_Update_Cutover_and_Uninstall.md, 06_Component_and_Package_Manifest.md)
- No duplicate manifest system introduced
- Planning profile packs remain separate from runtime lifecycle manifests
- Migration scaffolding documented as future work, not implemented
- Boundaries clearly recorded: installer scripts, state transitions, and lifecycle code are out of scope
- Verification confirms no duplicate installation story created
- Junior implementer can identify which lifecycle files are out of scope

# Acceptance Criteria

1. The task identifies what metadata is needed now versus what must wait for lifecycle/install work.
2. The task lists any schema, config, or docs locations that will own manifest data.
3. The task defines how migration-registry scaffolding avoids becoming a hidden installer implementation.
4. The task records template-installation assumptions explicitly.

# Notes

- Suitable with revision.
- The current pack mentions manifest and migration scaffolding, but the repository already has lifecycle/install concepts elsewhere, so duplication risk is real.
- This activity must connect to existing lifecycle and managed-baseline docs rather than inventing a second installation story.

# Implementation Notes

- Cross-reference lifecycle architecture docs and keep fields additive.
- Limit this phase to documented scaffolding, sample structure, and validation notes.
- Defer scripts and state transitions to later lifecycle work.


# Execution Checklist

Implementation type: documentation and scope control only. This task should avoid new runtime behavior.

Files to review before making changes:
- `docs/specifications/architecture/05_Installation_Update_Cutover_and_Uninstall.md`
- `docs/specifications/architecture/06_Component_and_Package_Manifest.md`
- `src/audiagentic/runtime/lifecycle/manifest.py`
- `src/audiagentic/runtime/lifecycle/fresh_install.py`
- `src/audiagentic/runtime/lifecycle/cutover.py`
- `docs/references/planning/planning-doc-surfaces.md`
- `docs/references/planning/planning-verification-matrix.md`

Steps:
1. Confirm what manifest and migration concepts already exist in lifecycle/runtime code.
2. Limit this task to planning-facing scaffolding notes and placeholders only.
3. If a proposed change duplicates installed-state manifest logic, stop and redirect it to lifecycle work.
4. Record where future planning metadata would live without introducing a second installation system.
5. Document the boundaries clearly in the task/spec/reference docs.

Do not change:
- runtime manifest schemas or lifecycle code unless a separate lifecycle task explicitly requires it
- installer scripts
- state transitions for install/update/cutover

Verification:
- `python tools/planning/tm.py validate`
- manual review that no duplicate manifest system has been introduced

Done means:
- this task leaves behind clear scaffolding notes
- no duplicate installation story is created
- a junior implementer can tell which lifecycle files are out of scope
