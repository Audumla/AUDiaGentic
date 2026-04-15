---
id: standard-0009
label: Planning layer enhancement impact standard
state: ready
summary: Default standard for changes to the planning layer that affect workflows,
  state semantics, MCP surfaces, indexing, validation, extracts, or other shared
  planning behavior.
---

# Standard

Default standard for enhancing or adjusting the AUDiaGentic planning layer when the change affects shared planning behavior rather than only one isolated document.

# Source Basis

This standard is derived from the repository's planning architecture, MCP wrapper behavior, workflow configuration, and the need to keep shared planning semantics coherent across code, config, and documentation surfaces.

Sources:

- Repository planning API and helper layers
- Repository MCP planning wrapper
- Repository workflow and validation configuration
- Existing planning standards for structure, migration, Python implementation, and component architecture

# Requirements

1. Planning-layer enhancements must define the canonical behavior in the planning core, not only in the MCP wrapper layer.
2. Changes to planning state semantics must identify which behavior belongs in workflow configuration, which belongs in core API and helper logic, and which belongs only in MCP-facing convenience surfaces.
3. If a change is state-based, the preferred model is to extend existing lifecycle and state machinery unless a separate public action is required for clarity, validation, or audit reasons.
4. Planning-layer changes must explicitly consider impact on:

   - workflow definitions and transitions
   - helper and API method signatures and semantics
   - MCP tool signatures and parity with the helper and API layer
   - validation rules
   - query, list, and next surfaces
   - show, extract, head, and read surfaces
   - indexing, event, and generated-artifact behavior

5. MCP wrappers must not invent different semantics from the underlying planning core; convenience tools are acceptable, but they must remain aligned with the canonical core behavior.
6. Compatibility-sensitive planning changes must state what happens to existing records, existing clients, and existing automation assumptions.
7. If a planning-layer change affects visibility, state filtering, metadata shape, or generated read surfaces, the expected behavior must be documented in the request, spec, or plan chain before implementation is treated as ready.
8. Shared planning enhancements must define what remains source of truth versus what is cached, indexed, derived, or convenience-only.
9. Verification for planning-layer enhancements must include the changed shared surfaces, not only the immediate implementation seam.
10. Planning-layer changes that introduce new components or redesign existing ones must comply with standard-0011 (component architecture): define layer placement, module contracts, config-driven behavior, and extension points before implementation begins.
11. New config schema introduced by planning-layer changes must document defaults, validation behavior, and what happens when the key is absent — per standard-0011 config-driven requirements.

# Default Rules

- Prefer extending existing state and query surfaces before adding new top-level methods.
- Add explicit convenience methods only when they materially improve clarity, discoverability, or required metadata handling.
- Keep MCP tool names, helper names, and docs aligned when shared behavior changes.
- Treat stale extracts, stale indexes, and outdated generated surfaces as real closure items when shared planning behavior changes.
- Attach this standard explicitly to requests, specs, and plans that change the planning layer rather than making it a universal default for all planning work.

# Verification Expectations

- Verify workflow and config changes if state semantics change.
- Verify helper and API behavior and MCP-facing behavior stay aligned.
- Verify validation, listing, and read surfaces affected by the change.
- Record any intentionally deferred downstream impacts such as automations, triggers, or generated artifacts.
- Verify architectural compliance per standard-0011 for any new components introduced.

# Non-Goals

- Requiring every documentation-only planning edit to perform system-level impact analysis.
- Forcing all planning changes to introduce new MCP tools.
- Replacing project-specific specs for individual planning enhancements.
