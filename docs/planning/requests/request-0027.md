---
id: request-0027
label: Enhance planning MCP with bulk update operations and result summarization
state: distilled
summary: Extend MCP batch operations to support multi-item updates, bulk state transitions,
  and result summarization to reduce agent token usage and round-trip calls
source: claude
current_understanding: Planning MCP currently optimizes for single-item reads (head,
  show, extract controls) but not for bulk operations. Agents frequently perform bulk
  state transitions, relinking, or updates. A multi-item batch operation and optional
  result summarization (counts only, not full payloads) would reduce token overhead
  for common agent workflows.
open_questions:
- Should tm_batch_update accept both single-item (current) and multi-item formats
  for backward compatibility?
- For result summarization, what minimal response shape best serves agents (counts
  vs ID list)?
- Should compound operations like create_and_link be included or deferred?
- What should be the maximum batch size per call to prevent abuse?
context: Current tm_batch_update only accepts single item with multiple operations.
  Agents making bulk state changes (e.g., marking 6 tasks done) must call tm_state()
  individually, generating 6 MCP calls and 6 response payloads. Multi-item batch and
  result summarization would dramatically reduce token usage.
standard_refs:
- standard-0001
spec_refs:
- spec-0044
meta:
  current_understanding: 'Spec-0044 complete with detailed design for: (1) multi-item
    batch update extension with backward compat, (2) bulk state transitions optimized
    for agent use, (3) result summarization flag for minimal payloads, (4) future
    compound operations pattern. Ready for implementation.'
---

# Understanding

Planning MCP currently optimizes for single-item reads (head, show, extract controls) but not for bulk operations. Agents frequently perform bulk state transitions, relinking, or updates. A multi-item batch operation and optional result summarization (counts only, not full payloads) would reduce token overhead for common agent workflows.

## Open Questions

- Should tm_batch_update accept both single-item (current) and multi-item formats for backward compatibility?
- For result summarization, what minimal response shape best serves agents (counts vs ID list)?
- Should compound operations like create_and_link be included or deferred?
- What should be the maximum batch size per call to prevent abuse?

## Notes
