---
id: spec-016
label: Knowledge Component Improvements Specification
state: draft
summary: Specification for addressing critical review findings in knowledge component
request_refs:
- request-015
task_refs: []
standard_refs:
- standard-0006
- standard-0005
---



# Purpose

Address critical review findings from the knowledge component integration review (2026-04-14). The component is architecturally sound but operationally unfinished. This specification defines improvements to add tests, refactor large modules, enhance search, add lifecycle management, and consolidate the MCP interface.

# Scope

**In Scope:**
- Add unit tests for core modules (events.py, sync.py, validation.py)
- Refactor events.py into separate concern modules
- Enhance lexical search with stemming, fuzzy matching, stopword filtering
- Add lifecycle management for LLM jobs and sync proposals
- Consolidate 28 MCP tools into 7-8 top-level tools
- Add integration tests for patches.py with planning system

**Out of Scope:**
- Changing the deterministic-first architecture
- Modifying the event-driven sync model
- Changing the config-driven registry approach
- Replacing Markdown-based storage

# Requirements

## R1: Test Coverage

**Priority:** HIGH

Add unit tests for:
- `events.py`: Event scanning, filtering, normalization, state management
- `sync.py`: Drift detection, fingerprinting, proposal generation
- `validation.py`: Vault validation rules, page compliance checks
- `search.py`: Search scoring, ranking, result filtering

**Coverage Target:** 70%+ for core modules

## R2: Module Refactoring

**Priority:** MEDIUM

Split `events.py` (413 lines) into:
- `events/scanning.py`: Event file scanning and reading
- `events/normalization.py`: Event format normalization
- `events/dispatch.py`: Adapter matching and dispatch
- `events/state.py`: Event state persistence

Each module < 150 lines, single responsibility.

## R3: Search Enhancement

**Priority:** MEDIUM

Enhance `search.py` (51 lines) with:
- Stemming (Porter Stemmer or similar)
- Fuzzy matching (Levenshtein distance or difflib)
- Stopword filtering (English common words)
- BM25 scoring (optional, replace simple token matching)

Maintain deterministic behavior (no external dependencies required).

## R4: Lifecycle Management

**Priority:** MEDIUM

**LLM Jobs:**
- Add job schema with timestamps (created_at, updated_at, expires_at)
- Add expiry/timeout configuration
- Add cleanup action for stale jobs
- Add atomic write (write to temp, then rename)
- Add corruption recovery (validate on load)

**Sync Proposals:**
- Add proposal status field (pending, accepted, rejected, merged)
- Add timestamp for creation and update
- Add cleanup action for old proposals
- Add proposal application workflow

## R5: MCP Tool Consolidation

**Priority:** LOW-MEDIUM

Consolidate 28 tools into 7-8 top-level tools:

| New Tool | Wraps Current Tools |
|----------|---------------------|
| `knowledge.get` | `knowledge.get_page` |
| `knowledge.search` | `knowledge.search_pages` |
| `knowledge.answer` | `knowledge.answer_question` |
| `knowledge.sync` | `knowledge.scan_drift`, `knowledge.generate_sync_proposals`, `knowledge.draft_sync_proposal` |
| `knowledge.events` | `knowledge.scan_events`, `knowledge.process_events`, `knowledge.record_event_baseline` |
| `knowledge.scaffold` | `knowledge.scaffold_page`, `knowledge.seed_from_manifest` |
| `knowledge.admin` | `knowledge.doctor`, `knowledge.validate`, `knowledge.status`, `knowledge.show_capability_contract`, `knowledge.show_install_profiles` |
| `knowledge.jobs` | `knowledge.submit_profile_job`, `knowledge.get_job_status`, `knowledge.get_job_result` |

Maintain backward compatibility via aliases during transition.

## R6: Performance Improvements

**Priority:** LOW

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
- [ ] Unit tests exist for events.py, sync.py, validation.py
- [ ] Test coverage >= 70% for core modules
- [ ] Tests run as part of CI/CD pipeline
- [ ] No test failures on existing functionality

## AC2: Module Refactoring
- [ ] events.py split into 4 modules
- [ ] Each module < 150 lines
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
- [ ] 28 tools consolidated to 7-8 top-level tools
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
- [Integration Request](../requests/request-014.md)
- [Integration Plan](../plans/plan-010-knowledge-component-integration-plan.md)
