# Installer v13 review findings

## Summary

The v13 pack improves architecture direction, but it is not yet clean enough to import as-is.

## Findings

1. `spec-0049` through `spec-0064` introduce new installer platform concepts but do not reference `standard-0011`.
   - This misses an explicit repo requirement from `standard-0006` for component-level architectural change.
   - Impact: modularity, layering, config-loading seams, and extension-point rules are implied rather than governed.

2. `wp-0020` is still too broad for safe packetization.
   - It combines architecture correction, CLI contract, target modeling, release packaging, migration, and verification in one work package.
   - Impact: weak ownership boundaries and harder review/implementation sequencing.

3. `wp-0020` has duplicate sequence values.
   - `task-0259` shares `5000`, `task-0260` shares `6000`, `task-0267` shares `7000`.
   - Impact: ambiguous ordering and lower planning-record quality.

4. Plan and work-package structure still mirror the document set more than execution seams.
   - Architecture normalization, CLI/reconcile flow, external target model, and verification are separate delivery seams and should be separate work packages.
   - Impact: makes the package harder for low-capability implementors to execute safely.

5. Current-product contracts versus installer-platform contracts are described, but import boundaries are not yet enforced in the plan structure.
   - Impact: implementors could still widen existing hardcoded product modules instead of adding registry/resolution seams.

## Recut goals

- add `standard-0011` where installer platform architecture is introduced
- split one large work package into four modular packages
- make migration boundaries explicit
- keep request and top-level plan aligned to current repo structure
- keep import path open without binding future targets to today's components
