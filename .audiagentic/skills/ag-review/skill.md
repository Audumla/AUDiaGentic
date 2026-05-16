---
name: ag-review
description: Use for canonical @ag-review launches. Performs read-focused validation and completeness review without adding implementation work.
---

# ag-review skill

Trigger:
- first non-empty line resolves to `ag-review` or a configured alias (`agr`, `r`, `review`)

Do:
- perform read-focused validation and completeness review
- identify blockers, missing tests, contract mismatches, and drift from tracked docs
- verify that release artifacts and tracked docs are synchronized with the job record
- produce a deterministic, scoped review report with clear findings
- flag ambiguity, missing evidence, or stale references explicitly

Do not:
- do not add implementation work unless the normalized request explicitly allows it
- do not broaden review into feature-scope changes
- do not mutate tracked docs or code files without approval
- do not hide drift behind vague summaries
