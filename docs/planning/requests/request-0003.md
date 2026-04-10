---
id: request-0003
label: Add archive functionality to planning core
state: captured
summary: Implement archive state workflow with tm_archive, tm_restore, and archive
  filtering for planning objects
current_understanding: "This request is the original archive-workflow intake for the planning core. It established the first archive-state direction and is now best understood as the historical umbrella behind the newer implementation-focused archive request chain."
open_questions:
  - Should this request remain the historical umbrella while request-0005 drives implementation, or should the archive intake be consolidated more explicitly?
  - Which archive behaviors belong to the older workflow-oriented chain versus the newer implementation-focused chain?
  - What compatibility rules must be preserved so archive support does not break existing planning queries and state handling?
---

# Understanding

This request is the original archive-workflow intake for the planning core. It established the first archive-state direction and is now best understood as the historical umbrella behind the newer implementation-focused archive request chain.

# Open Questions

- Should this request remain the historical umbrella while request-0005 drives implementation, or should the archive intake be consolidated more explicitly?
- Which archive behaviors belong to the older workflow-oriented chain versus the newer implementation-focused chain?
- What compatibility rules must be preserved so archive support does not break existing planning queries and state handling?

# Notes

- `spec-0003` and `wp-0004` capture the earlier archive-workflow framing, while `request-0005` with `spec-0023` and `plan-0009` now carries the cleaner implementation-ready slice.
- This request still matters for provenance, but it is no longer the best single source for the current archive build plan.
- If the team wants a cleaner archive story later, this request should either be explicitly marked historical or linked more clearly to the newer chain.
