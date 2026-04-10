---
id: request-0005
label: Archive functionality for planning items
state: captured
summary: Implement archive state and functions to archive older or redundant planning
  items while maintaining historical records
source: legacy-backfill
current_understanding: "This request is the current implementation-focused archive intake. It takes the earlier archive concept and narrows it into a concrete delivery slice for archive state support, archive helper functions, filtering, and metadata visibility."
open_questions:
  - Which archive behaviors are mandatory for the first pass versus safe to defer?
  - What should the default visibility of archived items be in list, next, show, and validation flows?
  - What evidence is enough to show archive metadata is preserved without breaking normal planning operations?
---

# Understanding

This request is the current implementation-focused archive intake. It takes the earlier archive concept and narrows it into a concrete delivery slice for archive state support, archive helper functions, filtering, and metadata visibility.

# Open Questions

- Which archive behaviors are mandatory for the first pass versus safe to defer?
- What should the default visibility of archived items be in list, next, show, and validation flows?
- What evidence is enough to show archive metadata is preserved without breaking normal planning operations?

# Notes

- `spec-0023`, `plan-0009`, and `wp-0009` are the current implementation chain for this request.
- This request is a better build entrypoint than `request-0003` because it is narrower and already aligned to the current task sequence (`task-0190` to `task-0194`).
- The key execution risk is changing the state/query model without making archive behavior obvious and reversible.
