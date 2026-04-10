---
id: request-0002
label: Comprehensive implementation docs migration
state: captured
summary: Migrate all docs/implementation content to planning structure with full reference
  resolution
current_understanding: "This request is the umbrella intake for migrating the old implementation-document surface into the planning structure with preserved references, archived backup content, and reader-facing entrypoints that point at the canonical planning docs."
open_questions:
  - Which remaining implementation-backup documents are still canonical versus historical only?
  - Which migration specs, plans, and tasks still need real content instead of placeholder sections?
  - What exact reader-facing entrypoints still need reference rewrites before the migration can be considered complete?
---

# Understanding

This request is the umbrella intake for migrating the old implementation-document surface into the planning structure with preserved references, archived backup content, and reader-facing entrypoints that point at the canonical planning docs.

# Open Questions

- Which remaining implementation-backup documents are still canonical versus historical only?
- Which migration specs, plans, and tasks still need real content instead of placeholder sections?
- What exact reader-facing entrypoints still need reference rewrites before the migration can be considered complete?

# Notes

- This request already fans out into a large migration chain, including the original comprehensive migration spec/plan/work-package and the later “remaining implementation docs” slice.
- The repo still keeps `docs/implementation_backup/` as the historical source set, so success is not just copying content; it is also making the planning surface the clear reader-facing source of truth.
- This request should be treated as the migration umbrella, with completion judged by canonical references, completeness of migrated planning objects, and the absence of misleading old entrypoints.
