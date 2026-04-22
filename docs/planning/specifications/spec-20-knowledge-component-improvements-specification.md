---
id: spec-20
label: Knowledge Component Improvements Specification
state: in_progress
summary: Specification for addressing critical review findings in knowledge component
request_refs:
- request-15
task_refs: []
standard_refs:
- standard-6
- standard-5
---
















# Purpose

Address critical review findings from the knowledge component integration review (2026-04-14). The component is architecturally sound but operationally unfinished. This specification defines improvements to add tests, refactor large modules, enhance search, add lifecycle management, and consolidate the MCP interface.

# Scope
**In Scope:**
- Add unit tests for core modules (events.py, sync.py, validation.py) — partial: 4 test files exist (~580 lines)
- Refactor events.py into separate concern modules — partial: split into 3 sub-modules, but each exceeds 150-line target
- Enhance lexical search with stemming, fuzzy matching, stopword filtering — pending verification
- Add lifecycle management for LLM jobs and sync proposals — pending verification
- Consolidate MCP tools — partial: 28→16 tools, target 7-8 not yet reached
- Add integration tests for patches.py with planning system — pending

**Out of Scope:**
- Changing the deterministic-first architecture
- Modifying the event-driven sync model
- Changing the config-driven registry approach
- Replacing Markdown-based storage
# Requirements
## R1: Test Coverage

**Priority:** HIGH
**Status:** PARTIAL — 4 test files exist (~580 lines total)

**Existing tests:**
- `test_search.py` (187 lines)
- `test_config.py` (80 lines)
- `test_event_state.py` (185 lines)
- `test_models.py` (128 lines)

**Missing tests:**
- `event_handlers.py` (385 lines)
- `event_scanner.py` (422 lines)
- `sync.py` (642 lines)
- `validation.py` (156 lines)

**Coverage Target:** 70%+ for core modules

## R2: Module Refactoring

**Priority:** MEDIUM
**Status:** PARTIAL — events.py split into 3 sub-modules

**Current state:**
- `events.py`: 43 lines (re-export shim)
- `event_handlers.py`: 385 lines
- `event_scanner.py`: 422 lines
- `event_state.py`: 210 lines

**Remaining:** Each sub-module exceeds 150-line target. Further decomposition needed.

## R3: Search Enhancement

**Priority:** MEDIUM
**Status:** PENDING VERIFICATION

`search.py` grew from 51 → 166 lines. Verify if stemming, fuzzy matching, stopword filtering, or BM25 were applied.

## R4: Lifecycle Management

**Priority:** MEDIUM
**Status:** PENDING VERIFICATION

`lifecycle.py` exists in source. Verify if it covers job expiry, proposal status, cleanup.

## R5: MCP Tool Consolidation

**Priority:** LOW-MEDIUM
**Status:** PARTIAL — 28 → 16 tools registered

**Target:** 7-8 top-level tools with backward compatibility aliases.
**Current:** 16 tools in `mcp_server.py`. Consolidation table from original spec still applies.

## R6: Performance Improvements

**Priority:** LOW
**Status:** PENDING

- Incremental event fingerprinting (cache in state file)
- Auto-generate vault index from page metadata
- Add integration test for patches.py with planning system
# Constraints

- Maintain deterministic-first design (LLM remains optional)
- No breaking changes to existing CLI interface
- No external dependencies for core functionality
- Maintain config-driven approach (no hardcoded values)
- Backward compatibility for MCP tools during transition

# Acceptance Criteria
## AC1: Test Coverage
- [x] Unit tests exist for search, config, event_state, models (4 files, ~580 lines)
- [ ] Unit tests exist for event_handlers, event_scanner, sync, validation
- [ ] Test coverage >= 70% for core modules
- [ ] Tests run as part of CI/CD pipeline
- [ ] No test failures on existing functionality

## AC2: Module Refactoring
- [x] events.py split into sub-modules (3 modules)
- [ ] Each module < 150 lines (current: 385, 422, 210)
- [ ] Single responsibility per module
- [ ] All existing functionality preserved
- [ ] Tests pass after refactoring

## AC3: Search Enhancement
- [ ] Stemming implemented and tested
- [ ] Fuzzy matching implemented and tested
- [ ] Stopword filtering implemented and tested
- [ ] Search quality improved (measured by test queries)
- [ ] No performance regression

## AC4: Lifecycle Management
- [ ] LLM job schema with timestamps
- [ ] Job expiry and cleanup working
- [ ] Atomic write for job state
- [ ] Proposal status field added
- [ ] Proposal cleanup action working
- [ ] No accumulation of stale jobs/proposals

## AC5: MCP Consolidation
- [ ] 28 tools consolidated to 7-8 top-level tools (current: 16)
- [ ] Backward compatibility via aliases
- [ ] All functionality preserved
- [ ] MCP server tests pass
- [ ] Documentation updated

## AC6: Documentation
- [ ] README.md reflects all changes
- [ ] CRITICAL_REVIEW.md updated with completion status
- [ ] Knowledge pages updated if affected
- [ ] Migration guide for MCP tool changes
# Implementation Notes

**Order of Implementation:**
1. Add tests (R1) - Foundation for safe refactoring
2. Add lifecycle management (R4) - Prevents state rot
3. Refactor events.py (R2) - With test safety net
4. Enhance search (R3) - Independent improvement
5. Consolidate MCP tools (R5) - Interface cleanup
6. Performance improvements (R6) - Optimization

**Risk Mitigation:**
- Add tests before refactoring
- Maintain backward compatibility during MCP transition
- Incremental deployment of changes
- Integration tests for planning bridge

# References

- [Critical Review Document](../../docs/knowledge/docs/CRITICAL_REVIEW.md)
- [Knowledge System](../../docs/knowledge/pages/systems/system-knowledge.md)
- [Integration Request](../requests/request-14.md)
- [Integration Plan](../plans/plan-010-knowledge-component-integration-plan.md)

# Notes
Assessment on 2026-04-19: specification updated to reflect actual implementation state. Key changes:
- events.py already split (R2 partial) — sub-modules exceed 150-line target
- 4 test files exist (~580 lines) but missing coverage for event_handlers, event_scanner, sync, validation (R1 partial)
- MCP tools reduced from 28→16, target 7-8 not yet reached (R5 partial)
- R3 (search) and R4 (lifecycle) need verification against source
- spec-15 deleted as redundant duplicate
- request-15 open questions formally answered
