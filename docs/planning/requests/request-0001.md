---
id: request-0001
label: Refactor knowledge component hooks to use event-driven architecture
state: superseded
summary: Remove legacy hooks system from knowledge component and replace with event-driven
  architecture
source: audit
guidance: standard
current_understanding: Initial intake captured; requirements are understood well enough
  to proceed.
open_questions:
- What exact outcome is required?
- What constraints or non-goals apply?
- How will success be verified?
---



# Understanding

Initial intake captured; requirements are understood well enough to proceed.

# Open Questions

- What exact outcome is required?
- What constraints or non-goals apply?
- How will success be verified?
# Notes
Assessment on 2026-04-17: superseded by the current knowledge-component design adopted in `request-014`. Repository still intentionally uses knowledge hooks (`src/audiagentic/knowledge/hooks.py`, `.audiagentic/knowledge/sync/hooks.yml`, related docs), so this removal request is no longer the active direction.
