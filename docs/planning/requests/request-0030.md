---
id: request-0030
label: Require request linkage for every planning specification
state: captured
summary: Enforce that specifications cannot be created or retained without at least one valid request reference, and repair the current orphaned workflow-state spec.
source: codex
current_understanding: Specifications are design responses to tracked intake, so orphan specs weaken traceability, standards inheritance, and planning closure. The planning API, helper surface, MCP tools, and schema should require at least one request reference for spec creation.
open_questions:
  - Should validation also escalate existing orphan specs from warning-level drift to a hard error during full-repo validation?
  - Should relink or future unlink operations prevent removing the last request reference from an existing spec?
standard_refs:
  - standard-0001
  - standard-0009
spec_refs:
  - spec-0047
---

# Understanding

Specifications should always trace back to explicit intake. A spec without a request reference is a planning-layer integrity bug, not a valid steady state. The creation paths should reject orphan specs, and the existing workflow-state spec should be attached to a real request.

# Open Questions

- Should validation also escalate existing orphan specs from warning-level drift to a hard error during full-repo validation?
- Should relink or future unlink operations prevent removing the last request reference from an existing spec?

# Notes

This request repairs the current `spec-0047` orphan condition by attaching it to this intake and tightening the planning-layer guardrails so the same issue cannot recur through API, helper, or MCP creation paths.
