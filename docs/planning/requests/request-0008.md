---
id: request-0008
label: Fix planning API and MCP gaps revealed by coverage tests
state: closed
summary: 'Fix 23 failing tests across PlanningAPI and MCP: section-mode regex, wp
  move, request workflow, claims TTL, hook payloads, batch meta op, status shape,
  empty-list serialization, and root isolation'
current_understanding: 'Initial request intake captured: Implement fixes for 23 failing
  tests in test_planning_api_coverage.py and test_mcp_tool_calls.py: (1) section-mode
  content replacement regex, (2) wp move to contrib domain, (3) request state workflow
  (captured→draft), (4) claims TTL expiry enforcement, (5) hook event payload structure
  for review_stub/report_stub/note_stub, (6) batch operation meta op and tm_helper
  set_root interaction, (7) tm_status return shape, (8) MCP empty-list/None serialization
  via FastMCP (0 content blocks), (9) MCP subprocess root isolation via AUDIAGENTIC_ROOT
  env var or --root flag to enable mutation test isolation'
open_questions:
- Should FastMCP empty-list fix be a wrapper in each MCP tool function, or patched
  at the FastMCP response-serialization layer?
- Should claims TTL expiry purge expired records on read (lazy) or on a scheduled
  basis?
- Should AUDIAGENTIC_ROOT env var be the only isolation mechanism, or also support
  a --root CLI flag passed to the MCP server?
- Is captured -> draft a valid request workflow transition or should requests skip
  captured on creation?
---






# Understanding

23 tests fail in two new coverage suites (`test_planning_api_coverage.py` and `test_mcp_tool_calls.py`) plus 32 mutation tests are marked xfail due to MCP subprocess isolation not being implemented. The failures map to 9 distinct root causes across three layers: PlanningAPI bugs, MCP serialization issues, and a missing MCP root isolation mechanism.

**PlanningAPI bugs (12 failures):**
1. `update_content()` section-mode regex fails to bound section end correctly — corrupts sibling sections
2. `move()` fails for work-packages — path resolution inconsistency for wp domain
3. Request workflow missing `captured -> draft` transition in workflows.yaml
4. Claims TTL expiry not enforced — expired claims still block `next_items()` and appear in `claims()`
5. Hook event payloads for `review_stub`, `report_stub`, `note_stub` have wrong structure
6. Batch `meta` op in `_execute_batch_operations()` silently discarded — no frontmatter write
7. `tm.status()` return shape uses different keys than `{request, spec, plan, task, wp}`

**MCP serialization (11 failures):**
8. FastMCP emits 0 content blocks for empty list `[]` and `None` — clients cannot distinguish from void/error. Affects: `tm_validate`, `tm_claims`, `tm_next_tasks`, `tm_next_items`, `tm_pending_doc_updates`, `tm_standards`, `tm_get_doc_surface`, `tm_get_request_profile`

**MCP root isolation (32 xfail):**
9. MCP server `_bootstrap_repo_root()` always resolves via module file path markers, ignoring cwd when `tools/planning/tm_helper` is importable from the real repo. Needs `AUDIAGENTIC_ROOT` env var support.

# Open Questions
**1. FastMCP empty-list fix: Patch at serialization layer**
- The issue is systemic: FastMCP serializes Python lists as multiple content blocks (one per item), so empty lists produce 0 blocks
- Fix should be at the **serialization layer** (patching FastMCP's response handling or using a wrapper around the tool decorator) rather than wrapping each tool individually
- This ensures consistency across all tools and prevents future regressions

**2. Claims TTL expiry: Lazy purge on read**
- Claims are lightweight and checked frequently via `next_items()` and `claims()`
- **Lazy purge on read** is more efficient than scheduled basis for this use case
- Implement cleanup in `Claims._load()` or at start of `next_items()`/`claims()` methods
- Avoids background task complexity and ensures stale claims don't block operations

**3. Root isolation: Support both `AUDIAGENTIC_ROOT` env var AND `--root` CLI flag**
- **Env var** (`AUDIAGENTIC_ROOT`) is essential for MCP server contexts where CLI flags aren't available
- **CLI flag** (`--root`) is needed for direct CLI usage and testing
- Precedence: `--root` CLI flag > `AUDIAGENTIC_ROOT` env var > auto-detection via markers
- This provides maximum flexibility for different deployment scenarios

**4. Request workflow: `captured -> draft` is NOT valid; requests start at `captured`**
- Per `.audiagentic/planning/config/workflows.yaml`, the request workflow is: `captured -> distilled -> closed/superseded`
- Requests **do not** have a `draft` state; they start at `captured` (unlike specs/plans/tasks which start at `draft`)
- The question in the request is based on a misunderstanding; the fix is to remove any code expecting `captured -> draft` transition
# Notes

Failures were discovered by writing full surface-level tests before implementation — tests serve as the specification for this work. All 23 failures are genuine gaps, not test harness issues. The 32 xfail tests will become regular passing tests once root isolation is implemented.
