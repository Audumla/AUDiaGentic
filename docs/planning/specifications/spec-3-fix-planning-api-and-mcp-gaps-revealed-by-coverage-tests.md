---
id: spec-3
label: Fix planning API and MCP gaps revealed by coverage tests
state: in_progress
summary: 'Implementation specification for 9 fixes: section-mode regex, wp move, claims
  TTL, hook payloads, batch meta, status shape, empty-list serialization, and root
  isolation'
request_refs:
- request-7
task_refs:
- ref: task-227
---




# Purpose

Implement and verify the planning API and MCP fixes identified by the coverage-driven review in `request-7`, keeping the coverage suites as the primary evidence source for completion.

# Scope

- PlanningAPI behavior fixes covered by `test_planning_api_coverage.py`
- MCP response-shape fixes covered by `test_mcp_tool_calls.py`
- MCP subprocess root-isolation work needed to un-xfail isolated mutation tests
- Request/spec/plan/task documentation state updates that reflect actual implementation progress

Out of scope:
- Broader planning feature work unrelated to the coverage-driven defects
- Retiring exploratory stack-profile test artifacts tracked under later requests
- Changing the core request workflow model beyond what the existing tests require

# Requirements

1. `update_content()` section mode must replace or append section content without corrupting neighboring sections.
2. `move()` must support both tasks and work-packages across domains.
3. Claims must lazily purge expired entries so stale claims do not block reads.
4. Hook stub payloads must match the expected event structure for review/report/note actions.
5. Batch `meta` operations must persist to frontmatter.
6. `tm.status()` must return stable kind-key counts.
7. MCP tools returning empty lists or `None` must serialize to a usable response shape.
8. MCP mutation tests must be able to target an isolated project root through explicit root selection.

# Constraints

- Preserve backward compatibility for normal planning CLI and MCP usage.
- Do not weaken the current planning schema just to satisfy test fixtures.
- Keep the isolation mechanism explicit; it should not silently break auto-detection for normal repo use.
- Use the existing planning test modules as the verification surface rather than inventing a parallel one-off harness.

# Acceptance Criteria

1. Tasks `task-0190` through `task-0196` are complete and reflected as such in planning records only when corroborated by passing coverage tests.
2. Remaining root-isolation work is called out explicitly rather than hidden by closed request/spec states.
3. `python -m pytest tests/integration/planning/test_planning_api_coverage.py -q` passes.
4. `python -m pytest tests/integration/planning/test_mcp_tool_calls.py -q` passes implemented checks while the isolation-dependent class remains xfailed until root selection is added.
5. The request/spec/plan/wp/task chain accurately communicates that this slice is mostly implemented but not yet fully complete.
