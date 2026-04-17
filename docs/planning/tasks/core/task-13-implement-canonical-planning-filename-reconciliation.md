---
id: task-13
label: Implement canonical planning filename reconciliation
state: ready
summary: Make planning filename conventions config-driven, reconcile legacy files,
  repair references, and rebuild derived planning state through one maintenance path
domain: core
spec_ref: spec-5
standard_refs:
- standard-5
- standard-6
---





# Objective

Implement canonical planning filename reconciliation from config and expose one maintenance path that repairs references and rebuilds derived planning state.

# Deliverables
- Add config-owned canonical naming rules for planning filenames
- Update creation path to emit canonical filenames for all supported planning kinds
- Update reconcile/repair path to normalize legacy mixed-format files to canonical names
- Include reference repair in maintenance flow
- Expose one canonical API/MCP maintenance entry point for rebuild/cleanup
- Ensure existing admin maintenance paths delegate to or align with the canonical path
- Add tests for filename generation, migration, reference repair, and rebuild behavior
# Acceptance Criteria
1. New planning objects use canonical config-driven filenames automatically.
2. Reconcile path normalizes legacy mixed-format filenames.
3. Reference repair occurs as part of maintenance flow.
4. Canonical maintenance flow rebuilds indexes/extracts/derived state cleanly.
5. Existing maintenance/admin entry points do not diverge from canonical repair behavior.
6. Tests cover migration and lookup behavior after reconciliation.
# Implementation Notes

Use config as source of truth for filename conventions.
Avoid keeping separate implicit naming rules in create-path code and reconcile code.

Maintenance flow should leave planning in a clean post-repair state, including:
- canonical filenames
- repaired refs
- refreshed lookup/index artifacts
- refreshed extracts/derived state where applicable
- successful validate/verify results

If current `index`, `reconcile`, or internal rebuild paths overlap, consolidate around one canonical implementation path rather than adding more parallel cleanup logic.
