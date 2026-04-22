---
id: task-235
label: Enhance lexical search
state: draft
summary: Add stemming, fuzzy matching, stopword filtering to search.py
spec_ref: spec-20
parent_task_ref: wp-14
request_refs:
- request-15
standard_refs:
- standard-5
- standard-6
---










# Description
Upgrade lexical search so it is useful for real documentation lookup, not just literal token hits. Add stemming, stopword filtering, and a deterministic fuzzy boost path where available, then keep scoring predictable enough for tests and agent use.

# Acceptance Criteria
1. Search ignores common stopwords in ranking.
2. Search matches basic word variants through stemming or equivalent normalization.
3. Search uses deterministic fuzzy fallback when exact scoring is zero.
4. Search results remain stable across repeated runs with the same data.
5. Query snippets and match metadata remain useful for agent review.
6. No external service is required for search to function.

# Notes
- Favor lightweight standard-library implementations unless an existing optional dependency is already available.
- Keep scoring predictable so tests can assert ordering and match behavior.
