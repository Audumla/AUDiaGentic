---
id: standard-0001
label: Planning documentation and maintenance standard
state: ready
summary: Default standard for maintaining planning records and adjacent documentation as first-class, reviewable project assets.
---

# Standard

Default standard for how planning records and adjacent documentation should be written, maintained, and kept current in AUDiaGentic-based projects.

# Source Basis

This standard is derived from the Write the Docs guidance on docs-as-code, documentation principles, and style guidance, adapted for the repository's planning model.

Sources:
- https://www.writethedocs.org/guide/docs-as-code.html
- https://www.writethedocs.org/guide/writing/docs-principles.html
- https://www.writethedocs.org/style-guide.html

# Requirements

1. Planning records are maintained as versioned, reviewable text assets in the repository.
2. Documentation updates should happen alongside the relevant planning or implementation change, not as an afterthought.
3. Documentation must stay current. Incorrect documentation is treated as worse than missing documentation.
4. Planning items must use clear, stable labels and summaries so humans and tools can identify them quickly.
5. The scope, non-goals, and verification expectations for work should be visible in the planning record before implementation begins.
6. Documentation should be structured for skimmability:
- clear headings
- concise sections
- explicit examples where useful
- separation between reference material and explanatory material
7. Changes to documentation should follow the same quality expectations as code changes:
- version control
- review
- traceable ownership
- verification where practical

# Default Rules

- Prefer Markdown planning documents that are easy to diff and review.
- Keep acceptance criteria and verification steps explicit.
- Keep planning docs aligned with the actual repository structure and tool behavior.
- Do not claim implementation completeness where only scaffolding or review prep exists.

# Non-Goals

- defining execution workflow policy
- replacing project-specific architecture decisions
- forcing one universal prose style across all documentation surfaces
