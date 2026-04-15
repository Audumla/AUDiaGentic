---
id: request-007
label: Fix planning API and MCP gaps revealed by coverage tests
state: closed
summary: 'Fix 23 failing tests across PlanningAPI and MCP: section-mode regex, wp
  move, request workflow, claims TTL, hook payloads, batch meta op, status shape,
  empty-list serialization, and root isolation'
source: legacy-backfill
current_understanding: 'Coverage-driven planning fixes are mostly complete: the planning
  API and MCP surface now pass the coverage suite, but MCP subprocess root isolation
  via AUDIAGENTIC_ROOT/--root remains unimplemented and keeps the isolated mutation
  suite xfailed.'
open_questions:
- Implement MCP root isolation so mutation tests can run against a seeded temp project
  instead of resolving to the real repo.
meta:
  current_understanding: 'All hardening work complete and verified: API/MCP fixes
    implemented, root isolation working via AUDIAGENTIC_ROOT, extract efficiency controls
    in place, lean head() function exposed. All 170 tests passing (92 API + 78 MCP).'
  open_questions: []
---




# Understanding

This request drove a comprehensive hardening pass on the planning API and MCP surface, with all fixes now implemented and verified.

## Implemented and Verified

1. ✅ `update_content()` section-mode behavior — covered by passing regression tests
2. ✅ `move()` for work-packages — passes coverage tests
3. ✅ Claims TTL expiry — lazily purged on read
4. ✅ Hook payloads — `review_stub`, `report_stub`, `note_stub` match expected test shape
5. ✅ Batch `meta` operations — persist frontmatter updates
6. ✅ `tm.status()` — returns expected kind keys
7. ✅ MCP empty-list and `None` results — wrapped to preserve usable response shape
8. ✅ MCP subprocess root isolation — via `AUDIAGENTIC_ROOT` environment variable

## Root Isolation Implementation

The MCP server now supports isolated project roots:

- **In tm_helper.py**: `_find_project_root()` checks `AUDIAGENTIC_ROOT` env var first (lines 31-38)
- **In MCP server**: Calls `tm.set_root()` when `AUDIAGENTIC_ROOT` is set (audiagentic-planning_mcp.py lines 58-60)
- **Test validation**: All 31 mutation isolation tests in `TestMCPMutationIsolated` pass
- **No xfail markers**: Mutation tests run against isolated temp projects successfully

## Extract Efficiency Improvements

`extract()` now supports controls for reducing token usage:

- `include_body: bool = True` — Can skip full markdown body for metadata-only calls
- `write_to_disk: bool = True` — Can skip artifact write when only reading
- Exposed in MCP as full parameters, allowing callers to optimize token consumption

## Lean Metadata Surface

New `head(id)` function provides index-only metadata without markdown parsing:

- Returns only frontmatter fields from index
- No file I/O beyond index lookup
- Exposed in MCP as `tm_head` tool
- Lowest token cost for single-item reads

## Test Evidence

- `test_planning_api_coverage.py`: 92/92 PASS ✅
- `test_mcp_tool_calls.py`: 78/78 PASS ✅
  - TestMCPProtocol: 6 tests ✅
  - TestReadOnlyTools: 41 tests ✅
  - TestMCPMutationIsolated: 31 tests ✅
- No xfail markers remaining in mutation test suite

## Acceptance Criteria

- [x] All 7 original hardening fixes implemented and tested
- [x] MCP root isolation via AUDIAGENTIC_ROOT
- [x] Mutation test suite passes in isolation (31/31)
- [x] Extract controls (include_body, write_to_disk) exposed
- [x] Lean head() function implemented and exposed
- [x] All coverage tests passing
- [x] All MCP tool tests passing

# Open Questions

None — all implementation complete and verified.

# Notes

All work tracked by this request is complete and verified by passing test suites. The planning API and MCP surface are hardened and ready for production use.
