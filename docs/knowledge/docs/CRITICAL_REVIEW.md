# Critical Review: Knowledge Component

**Review Date:** 2026-04-14  
**Component:** `src/audiagentic/knowledge/`  
**Status:** Integrated, improvements tracked

## Summary

The knowledge component is a fully implemented optional knowledge vault system (~3,267 lines across 23 modules) providing Markdown-based knowledge pages, drift detection, event-driven sync with planning, lexical search, optional LLM integration, and both CLI and MCP interfaces.

**Verdict:** Architecturally coherent but operationally unfinished. The isolation model, deterministic-first approach, and config-driven registries are correct. However, there are significant gaps in testing, module organization, and lifecycle management that need addressing.

## What Was Fixed

### ✅ Applied Immediately (Architecture Review)

1. **README documentation drift** - Updated `src/audiagentic/knowledge/README.md` to reflect "fully implemented" status instead of "scaffold only"

2. **Bootstrap idempotency verified** - Confirmed `bootstrap.py` line 57-58 skips existing files unless `--force`:
   ```python
   if path.exists() and not force:
       continue
   ```

3. **Config path resolution verified** - `config.py` uses relative paths from configuration, not hardcoded schema paths

### ✅ Applied Immediately (Code Review)

4. **search.py word boundary matching** - Fixed substring false positives (e.g., "cat" matching "category"):
   - Changed from `if token in title` to regex word boundary matching
   - See: `docs/knowledge/docs/CODE_REVIEW_FIXES.md`

5. **validation.py duplicate ID grouping** - Fixed noisy duplicate error reporting:
   - Now groups all pages with same ID into single error message
   - See: `docs/knowledge/docs/CODE_REVIEW_FIXES.md`

6. **models.py tags parsing** - Fixed silent data loss for comma-separated tags:
   - Now parses "python, fastapi" string format in addition to list format
   - See: `docs/knowledge/docs/CODE_REVIEW_FIXES.md`

7. **markdown_io.py heading levels** - Fixed H1 and H3+ heading support:
   - Now parses all ATX heading levels (# through ######)
   - See: `docs/knowledge/docs/CODE_REVIEW_FIXES.md`

## Critical Issues (Tracked)

### 1. Zero Tests Across 3,267 Lines

**Risk:** HIGH  
**Impact:** Silent failures in file system operations, event processing, LLM calls

**Details:**
- 23 modules with no unit tests
- `events.py` (413 lines) and `llm.py` (473 lines) are most complex with zero coverage
- `doctor` command is runtime self-testing, not a substitute for unit tests

**Action:** Create test suite priority list
- [ ] `events.py` - event scanning, filtering, processing
- [ ] `sync.py` - drift detection, fingerprinting
- [ ] `validation.py` - vault validation rules
- [ ] `search.py` - search scoring and ranking

**Tracking:** See task backlog

### 2. events.py Has Too Many Responsibilities (413 Lines)

**Risk:** MEDIUM  
**Impact:** Hard to debug, no failure isolation

**Current Responsibilities:**
1. Event file scanning
2. Fingerprinting (SHA256)
3. Normalization transforms
4. State management
5. Adapter dispatch
6. Proposal generation

**Recommended Split:**
```
events/
  scanning.py      - Event file scanning and reading
  normalization.py - Event format normalization
  dispatch.py      - Adapter matching and dispatch
  state.py         - Event state persistence
```

**Action:** Refactor when test coverage is added

**Tracking:** See task backlog

### 3. Lexical Search Is Naive (51 Lines)

**Risk:** MEDIUM  
**Impact:** Search quality degrades as vault grows

**Current Implementation:**
- Token-split scoring with hardcoded weights
- No stemming
- No fuzzy matching
- No stopword filtering

**Expected Degradation:**
- 500+ page vault with overlapping terminology will return poor results
- `answer_question` MCP tool quality limited by retrieval layer

**Recommended Enhancements:**
- [ ] Add stemming (Porter Stemmer or similar)
- [ ] Add fuzzy matching (Levenshtein or difflib)
- [ ] Add stopword filtering
- [ ] Consider BM25 scoring instead of simple token matching

**Tracking:** See task backlog

### 4. LLM Job State Is Unstructured YAML

**Risk:** MEDIUM  
**Impact:** Stale jobs accumulate, no recovery from corruption

**Current State:**
- `llm-jobs.yml` tracks async job state manually
- No schema validation
- No timeout/expiry handling
- No cleanup mechanism
- No recovery path if file corrupted mid-write

**Recommended:**
- [ ] Add job schema with timestamps
- [ ] Add expiry/timeout configuration
- [ ] Add cleanup action for stale jobs
- [ ] Add atomic write (write to temp, then rename)
- [ ] Add corruption recovery (validate on load)

**Tracking:** See task backlog

### 5. 28 MCP Tools Is Too Many

**Risk:** LOW-MEDIUM  
**Impact:** MCP clients perform poorly with large tool surfaces

**Current Tools:** 28 exposed tools

**Recommended Consolidation:**
```
knowledge.get              - Get page by ID
knowledge.search           - Search pages
knowledge.answer           - Answer questions (wraps search + optional LLM)
knowledge.sync             - Sync operations (drift, proposals, events)
knowledge.scaffold         - Create pages
knowledge.admin            - Admin operations (doctor, validate, status)
knowledge.jobs             - Job management (submit, status, result)
```

**Action:** Consolidate into 7-8 top-level tools with subcommands

**Tracking:** See task backlog

### 6. Sync Proposals Have No Lifecycle

**Risk:** MEDIUM  
**Impact:** Proposals accumulate indefinitely

**Current State:**
- Proposals written to `knowledge/proposals/` as flat YAML files
- No "accept", "reject", "merge" states
- No cleanup mechanism
- Write-only state

**Recommended:**
- [ ] Add proposal status field (pending, accepted, rejected, merged)
- [ ] Add timestamp for creation and update
- [ ] Add cleanup action for old proposals
- [ ] Add proposal application workflow

**Tracking:** See task backlog

### 7. Events.py Fingerprinting Performance

**Risk:** LOW-MEDIUM  
**Impact:** Slow processing on large event files

**Current:** SHA256 on raw file content for every scan

**Recommended:**
- [ ] Use incremental hashing
- [ ] Cache fingerprints in state file
- [ ] Only re-hash changed files

**Tracking:** See task backlog

### 8. Vault Index.md Is Manual

**Risk:** LOW  
**Impact:** Won't scale past ~100 pages

**Current:** `knowledge/index.md` is a static manual file

**Recommended:**
- [ ] Auto-generate index from page metadata
- [ ] Add generation action to CLI
- [ ] Update on page create/delete

**Tracking:** See task backlog

## Moderate Issues (Verified)

| Issue | Status | Notes |
|-------|--------|-------|
| patches.py no integration test | ⚠️ Tracked | Add integration test with planning system |
| 4 YAML registries no fallback | ✅ By design | Project-owned configs, runtime defaults in `runtime_data/` |
| runtime_data/ no migration | ⚠️ Low priority | Version in contract, document migration path |

## Strengths (Confirmed)

✅ **Clean dependency isolation** - No imports from execution, channels, release, or planning. Event bridge is one-way via file polling.

✅ **Deterministic-first** - LLM is opt-in, not required. Correct design for a vault system.

✅ **Ownership contract explicit** - `capability_contract.yml` clearly separates runtime-owned from project-owned concerns.

✅ **Config-driven registries** - Importers, actions, execution, LLM all configurable via YAML without code changes.

✅ **Event-driven architecture** - Planning events bridge working (2132+ events processed).

✅ **Bootstrap idempotency** - Skips existing files unless `--force`.

## Recommendations

### Immediate (Next Sprint)
1. Add unit tests for `events.py`, `sync.py`, `validation.py`
2. Add proposal lifecycle (status, cleanup)
3. Consolidate MCP tools to 7-8 top-level tools

### Short Term (Next Quarter)
4. Split `events.py` into separate modules
5. Enhance search with stemming and fuzzy matching
6. Add LLM job lifecycle management

### Long Term
7. Auto-generate vault index
8. Add incremental event fingerprinting
9. Consider full-text search backend option

## References

- [Knowledge System Documentation](../../docs/knowledge/pages/systems/system-knowledge.md)
- [Code Review Fixes Applied](./CODE_REVIEW_FIXES.md)
- [Integration Request](../../docs/planning/requests/request-0032.md)
- [Integration Plan](../../docs/planning/plans/plan-0017-knowledge-component-integration-plan.md)
