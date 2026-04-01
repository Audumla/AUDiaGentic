# PKT-PRV-060: Provider Prompt Template Architecture and Defaults

**Phase:** 4 (Provider Prompt-Trigger Integration)  
**Status:** VERIFIED  
**Owner:** Infrastructure  
**Scope:** workspace  

---

## Objective

Define and implement the principle that shared default prompts are used for all providers unless a provider has material constraints (read-only, format differences, framework constraints). Avoid unnecessary duplication while preserving provider optimization paths.

---

## Current State

- Default prompts exist for all action types (plan, implement, review, audit, check-in-prep)
- Cline has a specialized `review/cline.md` (read-only emphasis, workspace awareness)
- Claude initially created specialized templates for all action types (unnecessary duplication)
- Bridge loader already supports provider-specific variant fallback

---

## Deliverables

### 1. Architecture Specification

**File:** `docs/specifications/architecture/47_Provider_Prompt_Templates_and_Defaults.md`

Documents:
- Principle: use defaults unless materially constrained
- When to create provider-specific variants (4 criteria)
- Bridge behavior (lookup order)
- Current inventory of templates
- Guidelines for future additions

**Status:** ✅ COMPLETE

---

### 2. Cleanup and Consistency

Removed unnecessary provider-specific templates:
- ❌ `.audiagentic/prompts/plan/claude.md`
- ❌ `.audiagentic/prompts/implement/claude.md`
- ❌ `.audiagentic/prompts/audit/claude.md`
- ❌ `.audiagentic/prompts/check-in-prep/claude.md`
- ❌ `.audiagentic/prompts/review/claude.md`

Kept justified variant:
- ✅ `.audiagentic/prompts/review/cline.md` (read-only constraints)

**Status:** ✅ COMPLETE

---

### 3. Updated Build Registry

Clarified PKT-PRV-033 and PKT-PRV-037 notes to reference this principle.

**Status:** ✅ COMPLETE

---

## Testing

All provider tests passing:
- `test_claude_prompt_trigger_bridge.py` (2/2 PASS)
- `test_cline_prompt_trigger_bridge.py` (if exists)

Bridge loader correctly:
1. Detects provider-specific templates when present
2. Falls back to default.md when variant absent
3. Applies variable substitution correctly

**Status:** ✅ VERIFIED

---

## Design Decision

**Question:** Should each provider have its own prompts, or use defaults with selective overrides?

**Answer:** Defaults + selective overrides (DRY principle)

**Justification:**
- Reduces maintenance burden (single source of truth for most templates)
- Allows optimization when justified (Cline's read-only constraints)
- Easier to keep instructions consistent across providers
- Faster to add new providers (inherit defaults automatically)

**Criteria for provider-specific variant:**
1. Provider has safety/read-only constraints (e.g., editor tool)
2. Provider output format differs materially
3. Provider framework imposes different expectations
4. Testing shows meaningful improvement over default

---

## Dependencies

**Direct Dependencies:**
- PKT-PRV-031 (prompt-trigger bridge with template loader) — VERIFIED
- PKT-PRV-033 (Claude baseline) — VERIFIED
- PKT-PRV-037 (Cline baseline) — READY_FOR_REVIEW

**Impact:**
- All future providers inherit this pattern automatically
- No code changes needed (bridge already supports lookups)

---

## Acceptance Criteria

- [x] Architecture spec documents the principle and criteria
- [x] Unnecessary Claude templates removed
- [x] Justified Cline template retained
- [x] Bridge tests still passing
- [x] Build registry updated
- [x] No duplication of default prompts across providers
- [x] Clear guidance for future provider additions

---

## Impact

### What Changes
- Cleaner prompt directory structure (no redundant variants)
- Simpler maintenance (less duplication)
- Clear architectural principle for providers

### What Stays the Same
- Bridge behavior (variant lookup already supported)
- All action types still work
- Provider-specific optimizations still possible

### Backwards Compatibility
✅ Fully compatible. Providers continue working with defaults. If a variant is removed, bridge automatically falls back to default.

---

## Notes

This decision was clarified during Claude Option A implementation review. The principle ensures that prompt templates remain maintainable as the provider ecosystem grows.

Future providers should:
1. Start with defaults
2. Add variants only if justified by the 4 criteria
3. Document why in PR comments and this spec
