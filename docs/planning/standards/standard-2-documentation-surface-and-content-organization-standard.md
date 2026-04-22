---
id: standard-2
label: Documentation surface and content organization standard
state: ready
summary: Default standard for how AUDiaGentic planning and project-facing documentation
  should be structured, named, and maintained across surfaces.
---







# Standard

Default standard for planning-related documentation surfaces and content organization in AUDiaGentic-based projects.

# Source Basis

This standard is derived from Diataxis and adapted for AUDiaGentic planning and template-installation needs.

Sources:

- [Diataxis — A systematic approach to technical documentation](https://diataxis.fr/)
- Architecture docs governing template ownership and managed surfaces in this repository

# Requirements

1. Documentation surfaces must be explicit and human-readable. A project should not hide core documentation behind opaque generated output.
2. Documentation families must stay distinct:

   - tutorials and how-to guidance belong in project-facing help docs
   - reference material belongs under `docs/references/`
   - specifications and architecture material remain in their canonical specification locations
   - planning objects remain under `docs/planning/`

3. Each managed documentation surface must declare its ownership mode using the repository vocabulary:

   - `manual`
   - `hybrid`
   - `managed`
   - optional `seed_on_install`

4. `README.md` and `CHANGELOG.md` must be treated as high-sensitivity surfaces because installed projects may already own them.
5. New documentation surfaces must be additive and template-safe. They must not assume this repository is a standalone application.
6. Reference documentation must have a clear entrypoint and must remain separate from release ledgers, specifications, and planning records.
7. Section and subsection navigation is an ergonomic helper only unless the underlying planning API provides a stronger structured model. Docs must not overstate determinism.
8. Supporting docs in this phase are structured sidecar docs, not first-class planning kinds.

# Default Rules

- Prefer concise, task-oriented reference docs over large narrative dumps.
- Keep documentation queryable through planning helper and MCP surfaces where practical.
- Align documentation labels and examples with the real file paths used in the repository.
- Document implementation limits honestly when behavior is best-effort.

# Non-Goals

- Defining installer behavior.
- Redefining execution workflow profiles.
- Widening planning object kinds beyond the current model.
