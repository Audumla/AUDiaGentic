---
id: request-0008
label: Fix planning API and MCP gaps revealed by coverage tests
state: distilled
summary: 'Fix 23 failing tests across PlanningAPI and MCP: section-mode regex, wp
  move, request workflow, claims TTL, hook payloads, batch meta op, status shape,
  empty-list serialization, and root isolation'
source: legacy-backfill
current_understanding: 'Coverage-driven planning fixes are mostly complete: the
  planning API and MCP surface now pass the coverage suite, but MCP subprocess root
  isolation via AUDIAGENTIC_ROOT/--root remains unimplemented and keeps the isolated
  mutation suite xfailed.'
open_questions:
- Implement MCP root isolation so mutation tests can run against a seeded temp project
  instead of resolving to the real repo.
---






# Understanding

This request started as a nine-fix hardening pass driven by the planning coverage suites. Review of the current code and test surface shows that the PlanningAPI and MCP behavior fixes are largely implemented, while MCP subprocess root isolation remains the open slice.

**Implemented and verified:**
1. `update_content()` section-mode behavior covered by passing regression tests
2. `move()` for work-packages now passes coverage tests
3. Claims TTL expiry is lazily purged on read
4. Hook payloads for `review_stub`, `report_stub`, and `note_stub` match the expected test shape
5. Batch `meta` operations persist frontmatter updates
6. `tm.status()` returns the expected kind keys
7. MCP empty-list and `None` results are wrapped to preserve a usable response shape

**Still open:**
8. MCP subprocess root isolation via `AUDIAGENTIC_ROOT` and/or `--root` for isolated mutation tests

**Evidence reviewed:**
- `python -m pytest tests/integration/planning/test_planning_api_coverage.py -q` passes
- `python -m pytest tests/integration/planning/test_mcp_tool_calls.py -q` passes its implemented checks, with the isolation-dependent mutation class still xfailed
- the xfail marker in `test_mcp_tool_calls.py` still explicitly states root isolation is not implemented

# Open Questions
The remaining design decision is implementation detail rather than product uncertainty: support isolated MCP mutation tests by honoring `AUDIAGENTIC_ROOT`, `--root`, or both without regressing normal root bootstrap behavior.
# Notes

Failures were discovered by writing full surface-level tests before implementation, and those tests continue to be the best evidence of what is actually complete.

This request was previously marked closed prematurely. It has been moved back to `distilled` because the root-isolation slice remains open even though the broader API/MCP hardening work is substantially complete.
