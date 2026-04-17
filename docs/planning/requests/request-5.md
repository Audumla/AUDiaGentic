---
id: request-5
label: Sensitive data detection and review for planning items
state: closed
summary: Implement optional security review that detects sensitive information (passwords,
  internal server names, PII, credentials) in planning requests, specifications, tasks,
  and work-packages, with ability to override for known test credentials
source: legacy-backfill
current_understanding: 'This request captures an exploratory but valuable planning-safety
  feature: detecting likely secrets and sensitive data in planning content before
  that material becomes part of tracked project records. It is related to secret-management
  policy, but it does not yet have a dedicated implementation spec or plan.'
open_questions:
- 'Which content surfaces should be checked first: frontmatter, markdown body, attachments,
  or generated runtime artifacts?'
- Should the first phase be advisory-only, validation-time warning, or a blocking
  review gate?
- How should approved test credentials, fixtures, or known-safe examples be allow-listed
  without weakening the review?
spec_refs:
- spec-009
meta:
  open_questions: []
  current_understanding: 'Lightweight v1 scope defined: cursory regex-based detection
    for AWS keys, API keys, passwords, bearer tokens in markdown body only; emit as
    non-blocking warnings in validation. Designed for quick implementation, extendable
    to frontmatter/attachments/allow-listing in future versions.'
---







# Understanding

This request captures an exploratory but valuable planning-safety feature: detecting likely secrets and sensitive data in planning content before that material becomes part of tracked project records. It is related to secret-management policy, but it does not yet have a dedicated implementation spec or plan.

# Open Questions

- Which content surfaces should be checked first: frontmatter, markdown body, attachments, or generated runtime artifacts?
- Should the first phase be advisory-only, validation-time warning, or a blocking review gate?
- How should approved test credentials, fixtures, or known-safe examples be allow-listed without weakening the review?

# Notes

- This request is still early-stage compared with the others; it does not yet have a dedicated spec, plan, or work package linked to it.
- The closest existing context is the repository’s secret-management and contract guidance, especially around keeping secrets out of tracked configuration and docs.
- The next sensible step for this request is a focused spec that defines scope, detection surfaces, enforcement mode, and override policy before implementation starts.
