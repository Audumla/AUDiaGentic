---
id: request-0004
label: MCP layer efficiency improvements and usage enforcement
state: captured
summary: Add wrapper functions, templates, and guidance to make MCP layer as efficient
  as direct file edits while ensuring consistent usage for audit trail and validation
source_refs:
  - spec-0021
  - spec-0022
  - plan-0007
  - plan-0008
  - wp-0005
  - wp-0006
  - docs/references/planning/planning-mcp-change-first.md
  - tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py
current_understanding: "This request drives the planning MCP and helper ergonomics work: improve read and update flows, reduce unnecessary direct edits, and make the planning surface efficient enough that agents can prefer it without losing auditability or validation safety."
open_questions:
  - Which remaining planning operations still require direct file edits because the MCP or helper layer cannot mutate the needed metadata cleanly?
  - How strongly should agent guidance enforce MCP-first behavior versus allowing pragmatic direct edits for unsupported cases?
  - Where should the line stay between a thin planning MCP and a more opinionated workflow surface?
---

# Understanding

This request drives the planning MCP and helper ergonomics work: improve read and update flows, reduce unnecessary direct edits, and make the planning surface efficient enough that agents can prefer it without losing auditability or validation safety.

# Source Refs

- spec-0021
- spec-0022
- plan-0007
- plan-0008
- wp-0005
- wp-0006
- docs/references/planning/planning-mcp-change-first.md
- tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py

# Open Questions

- Which remaining planning operations still require direct file edits because the MCP or helper layer cannot mutate the needed metadata cleanly?
- How strongly should agent guidance enforce MCP-first behavior versus allowing pragmatic direct edits for unsupported cases?
- Where should the line stay between a thin planning MCP and a more opinionated workflow surface?

# Notes

- This request now spans both the implementation-pack ergonomics work and the planning-surface usability work that followed it.
- `plan-0008` is already marked done, so parts of this request are satisfied; the remaining value is as provenance for the MCP-first direction and for tracking the unsupported cases that still force direct edits.
- The most important unresolved gap is still mutation coverage for some planning metadata, not basic discovery or read-only MCP access.
