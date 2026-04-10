---
id: request-0005
label: Archive functionality for planning items
state: distilled
summary: Implement archive state and functions to archive older or redundant planning
  items while maintaining historical records
source: legacy-backfill
current_understanding: This request is the current implementation-focused archive
  intake. It takes the earlier archive concept and narrows it into a concrete delivery
  slice for archive state support, state-driven archive/restore behavior, default
  archive filtering, validation behavior, and archive metadata visibility. It supersedes
  request-0003 as the active implementation intake while preserving that request
  as historical provenance.
open_questions:
- Are there any compatibility constraints from legacy planning queries or state transitions
  that need to be called out more explicitly before implementation is closed?
- What test evidence is sufficient to demonstrate archive metadata persistence and
  non-breaking behavior across list, show, validate, archive, and restore flows?
standard_refs:
- standard-0001
- standard-0009
meta:
  current_understanding: Archive functionality implementation ready to begin. Spec-0023
    finalized, plan-0009 and wp-0009 ready, all 5 tasks prepared for implementation.
---



# Understanding

This request is the current implementation-focused archive intake. It takes the earlier archive concept from `request-0003` and narrows it into a concrete delivery slice for archive state support, state-driven archive/restore behavior, default archive filtering, validation behavior, and archive metadata visibility.

# Open Questions

- Are there any compatibility constraints from legacy planning queries or state transitions that need to be called out more explicitly before implementation is closed?
- What test evidence is sufficient to demonstrate archive metadata persistence and non-breaking behavior across list, show, validate, archive, and restore flows?

# Notes

- `spec-0023`, `plan-0009`, and `wp-0009` are the current implementation chain for this request.
- `request-0003` remains the historical umbrella and provenance record for the earlier archive-workflow framing, but `request-0005` is the active implementation intake.
- The first-pass behavior is already defined by the linked implementation chain: add the `archived` state, keep archive and restore semantics state-based in the planning core, exclude archived items from `tm_list()` by default unless explicitly requested, relax cross-reference validation for archived items, and expose archive metadata in `tm_show()`.
- This request is a better build entrypoint than `request-0003` because it is narrower and already aligned to the current task sequence (`task-0190` to `task-0194`).
- The key execution risk is changing the state/query model without making archive behavior obvious and reversible.
