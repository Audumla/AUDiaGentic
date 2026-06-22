---
id: LSP16
order: 16
plan: unknown
state: draft
wave: W5.2
---

# Mandatory disk→buffer re-sync before file-scoped query

## Wave 5 — Diagnostics v2 (Phase 1)

Single enforced path: re-read disk → `didChange` (bump version) → then query.

**Depends:** LSP11, LSP12
