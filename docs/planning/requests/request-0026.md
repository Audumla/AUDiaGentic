---
id: request-0026
label: 'MCP mutation coverage gaps: operations requiring direct file edits'
state: closed
summary: Identify and close gaps in MCP/helper mutation coverage that currently force
  direct file edits; clarify MCP-first enforcement policy and scope boundary
source: claude
current_understanding: 'The planning MCP surface is efficient for read operations
  and basic mutations (state, label, summary, sections). Remaining gaps block full
  MCP-first workflows: certain planning metadata mutations have no clean MCP/helper
  path.'
open_questions:
- Which specific planning operations require direct file edits today?
- Why can't these be mutated via MCP/helper (design constraint vs implementation gap)?
- Should MCP-first be mandatory, recommended, or optional guidance?
- 'What is the target scope: thin wrapper or opinionated workflow surface?'
context: 'request-0004 identified unresolved gaps in planning MCP/helper mutation
  coverage. This request narrows focus to: (1) identify which planning operations
  still require direct file edits and why, (2) decide MCP-first enforcement policy,
  (3) clarify MCP layer scope/opinionation level.'
standard_refs:
- standard-0001
meta:
  open_questions: []
---

# Understanding

Extracted from request-0004 to assess whether MCP mutation coverage has actual gaps requiring closure. Analysis shows no concrete blockers: all currently mutable planning metadata has MCP/helper paths.

# Findings

**Current MCP mutation tools cover:**
- Metadata updates (label, summary, sections)
- Reference updates (spec_refs, task_refs, request_refs, standard_refs)
- State transitions
- Domain/archive claims
- Batch atomic operations

**No operations identified that require direct file edits.** Archive metadata gaps (archived_at, archived_by, etc.) are being addressed by request-0005 task-0194.

# Conclusion

No actual mutation coverage gaps exist in the current planning MCP surface. The three open questions from request-0004 (which operations need direct edits, enforcement policy, scope boundary) are speculative rather than derived from concrete blockers.

This request should remain closed unless future work identifies specific operations that cannot be mutated via MCP/helper layer.

# Open Questions

None — assessment complete.

# Notes

Request created as extraction from request-0004 but closed immediately upon finding no actual gaps. Revisit only if new planning metadata is added that lacks MCP mutation support.
