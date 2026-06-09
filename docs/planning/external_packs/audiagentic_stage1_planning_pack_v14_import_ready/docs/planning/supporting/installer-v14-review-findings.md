# Installer v13 review findings

## Status note

This is a historical review of the predecessor v13 pack.

The findings below intentionally use the predecessor pack's original IDs, not this rewritten copy's IDs.

## Summary

The v13 pack improved architecture direction, but it was not clean enough to import as-is.

## Findings

1. `spec-0049` through `spec-0064` introduced installer platform concepts but did not reference `standard-11`.
   - This missed an explicit repo requirement from `standard-6` for component-level architectural change.
   - Impact: modularity, layering, config-loading seams, and extension-point rules were implied rather than governed.

2. `wp-0020` was too broad for safe packetization.
   - It combined architecture correction, CLI contract, target modeling, release packaging, migration, and verification in one work package.
   - Impact: weak ownership boundaries and harder review or implementation sequencing.

3. `wp-0020` had duplicate sequence values.
   - `task-0259` shared `5000`, `task-0260` shared `6000`, and `task-0267` shared `7000`.
   - Impact: ambiguous ordering and lower planning-record quality.

4. Plan and work-package structure mirrored the document set more than execution seams.
   - Architecture normalization, CLI and reconcile flow, external target model, and verification are separate delivery seams and should be separate work packages.
   - Impact: made the package harder for low-capability implementors to execute safely.

5. Current-product contracts versus installer-platform contracts were described, but not enforced clearly enough in plan structure.
   - Impact: implementors could still widen existing hardcoded product modules instead of adding registry and resolution seams.

## Recut goals

- add `standard-11` where installer platform architecture is introduced
- split one large work package into four modular packages
- make migration boundaries explicit
- keep request and top-level plan aligned to current repo structure
- keep import path open without binding future targets to today's components
