---
id: plan-15
label: Knowledge Component Improvements Plan
state: in_progress
summary: Plan for implementing knowledge component improvements from critical review
spec_refs:
- spec-20
request_refs:
- request-15
work_package_refs: []
standard_refs:
- standard-6
---










# Objectives
1. Add comprehensive test coverage for knowledge component — partial: 4 test files exist (~580 lines), missing event_handlers, event_scanner, sync, validation
2. Split events.py sub-modules into < 150-line modules — partial: split into 3 modules (385, 422, 210 lines), further decomposition needed
3. Enhance search from token-based to fuzzy/BM25 approach — pending verification
4. Implement lifecycle tracking for proposals and jobs — pending verification
# Delivery Approach
1. **Phase 1 (Immediate)**: Complete test coverage for remaining modules
   - Tests for event_handlers (385 lines), event_scanner (422 lines), sync (642 lines), validation (156 lines)
   - Further decompose event sub-modules to < 150 lines each

2. **Phase 2 (Follow-up)**: Search enhancement + lifecycle verification
   - Verify/search enhancement implementation status
   - Verify/lifecycle management implementation status
   - Complete any missing functionality

3. **Phase 3 (Polish)**: MCP consolidation + integration tests
   - Consolidate 16 MCP tools to 7-8 top-level tools
   - End-to-end test flows
   - Integration tests for patches.py with planning system
# Dependencies

- spec-16 (Knowledge Component Improvements Specification) for detailed requirements
- standard-6 for test structure/coverage expectations
- No blocking external dependencies
