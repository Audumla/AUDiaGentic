---
id: request-15
label: Knowledge Component Improvements
state: distilled
summary: 'Address critical review findings: add tests, split events.py, enhance search,
  add lifecycle management, consolidate MCP tools'
source: 'Critical Review: Knowledge Component (2026-04-14)'
guidance: standard
current_understanding: 'Knowledge component integrated successfully but has gaps:
  zero tests, events.py too large (413 lines), naive search, no lifecycle for proposals/jobs,
  28 MCP tools too many. README updated, bootstrap idempotency verified, config paths
  verified. Need to track improvements.'
open_questions:
- What is the priority order for adding tests?
- Should MCP consolidation happen before or after tests?
- 'What search enhancement approach: BM25 vs fuzzy matching?'
meta:
  request_type: feature
  spec_refs:
  - spec-20
standard_refs:
- standard-1
spec_refs:
- spec-19
- spec-20
---














# Understanding

Knowledge component integrated successfully but has gaps: zero tests, events.py too large (413 lines), naive search, no lifecycle for proposals/jobs, 28 MCP tools too many. README updated, bootstrap idempotency verified, config paths verified. Need to track improvements.

# Open Questions
1. What is the priority order for adding tests?
**Answered:** Tests first (R1 is HIGH priority, foundation for safe refactoring).

2. Should MCP consolidation happen before or after tests?
**Answered:** MCP consolidation already implemented via grouped knowledge MCP operations (28→16 tools). Marked as stale-complete.

3. What search enhancement approach: BM25 vs fuzzy matching?
**Answered:** spec-16 R3 includes both stemming and fuzzy matching as in-scope. Evaluation deferred to Phase 2 of plan-11.
# Problem



# Desired Outcome



# Constraints


# Notes
Assessment on 2026-04-17: request remains valid and open, but its remaining scope is narrower than originally described. Real remaining work is tests, `events.py` refactor, search improvements, and lifecycle cleanup. MCP consolidation is already implemented via grouped knowledge MCP operations, so that task was closed as stale-complete.
