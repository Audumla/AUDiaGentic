# Phase 0.3 Refactor Artifacts

This directory holds the working artifacts required by the Phase 0.3 repository refactor checkpoint.

Expected files:

- `repository-inventory.md`
- `migration-map.md`
- `ambiguity-report.md`
- `public-import-surface.md`
- `final-validation-report.md`

Templates:

- `repository-inventory.template.md`
- `migration-map.template.md`
- `ambiguity-report.template.md`
- `public-import-surface.template.md`
- `final-validation-report.template.md`

Rules:

- `PKT-FND-010` owns the first four files.
- `PKT-FND-013` owns `final-validation-report.md`.
- Do not treat these as optional notes; they are part of the refactor contract.
- Keep them current as the refactor moves from inventory to freeze to code motion to cleanup.
- Instantiate the live artifacts from the templates rather than inventing ad hoc shapes mid-refactor.
