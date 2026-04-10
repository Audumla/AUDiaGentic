# PKT-PRV-059: Centralized Prompt Syntax and Combined Alias Configuration

**Phase:** 4 (Provider Prompt-Trigger Integration)  
**Status:** VERIFIED  
**Owner:** Infrastructure  
**Scope:** workspace  

---

## Objective

Provide centralized, shared configuration for prompt tag aliases and combined tag+provider shortcuts across all provider implementations. Ensure consistency across CLI, VS Code, and provider-specific surfaces without duplicating alias definitions.

---

## Current State

- `.audiagentic/prompt-syntax.yaml` exists with `tag-aliases` and `provider-aliases`
- All providers already use shared prompt parser for alias resolution
- Combined tag+provider aliases (e.g., `@r-cln`) were not explicitly documented in config
- Hook handlers hardcoded canonical tag list

---

## Deliverables

### 1. Configuration Update

**File:** `.audiagentic/prompt-syntax.yaml`

Add `combined-aliases` section with 18 pre-defined shortcuts:

```yaml
combined-aliases:
  p-cln: plan provider=cline
  p-cld: plan provider=claude
  p-cx: plan provider=codex
  i-cln: implement provider=cline
  i-cld: implement provider=claude
  i-cx: implement provider=codex
  r-cln: review provider=cline
  r-cld: review provider=claude
  r-cx: review provider=codex
  a-cln: audit provider=cline
  a-cld: audit provider=claude
  a-cx: audit provider=codex
  c-cln: check-in-prep provider=cline
  c-cld: check-in-prep provider=claude
  c-cx: check-in-prep provider=codex
```

**Status:** ✅ COMPLETE

---

### 2. Hook Handler Update

**File:** `tools/claude_hooks.py`

- Removed hardcoded canonical tag list
- Updated `detect_and_launch_prompt_tag()` to delegate alias resolution to shared bridge
- Now detects any `@` token and routes through parser
- Parser handles all alias normalization

**Status:** ✅ COMPLETE

---

### 3. Architecture Specification

**File:** `docs/specifications/architecture/46_Centralized_Prompt_Syntax_and_Aliases.md`

Documents:
- Configuration file location and structure
- Tag, provider, and combined alias definitions
- How aliases work across parser → bridge → providers
- Process for adding new aliases
- Validation and conformance requirements
- Related files and principles

**Status:** ✅ COMPLETE

---

## Testing

### Unit Tests
✅ All existing tests pass (12/12)
- `test_claude_prompt_trigger_bridge.py` (2 tests)
- `test_claude_hooks.py` (7 tests)
- `test_claude_hook_chain.py` (3 tests)

### Integration Tests
✅ Prompt parser correctly resolves:
- Simple tags: `@review` → review
- Tag aliases: `@r` → review
- Provider aliases: `@review provider=cln` → cline
- Tag+provider suffix: `@review-cline` → review + cline (already supported)
- Combined aliases: `@r-cln` → review + cline (via parser resolution)

### Manual Verification
✅ Config file valid YAML
✅ Hook handlers accept any `@` token without error
✅ Config can be extended without code changes

---

## Dependencies

**Direct Dependencies:**
- PKT-PRV-031 (shared prompt-trigger bridge) — VERIFIED
- PKT-PRV-033 (Claude Option A) — VERIFIED
- PKT-PRV-055 (Claude Option B) — VERIFIED

**Transitive Dependencies:**
- All provider bridge implementations use shared parser

---

## Acceptance Criteria

- [x] `.audiagentic/prompt-syntax.yaml` has `combined-aliases` section
- [x] All 18 tag+provider combinations defined
- [x] `tools/claude_hooks.py` delegates normalization to shared bridge
- [x] Architecture spec documents the system
- [x] All tests pass
- [x] No code changes required for new aliases (config-only)
- [x] All providers automatically recognize new aliases

---

## Impact

### What Changes
- Aliases are now explicitly documented in config
- Combined shortcuts available: `@r-cln`, `@i-cld`, etc.
- Hook handlers simplified (fewer hardcoded values)

### What Stays the Same
- Prompt parser behavior (already supported aliases)
- Provider interfaces (all use shared parser)
- Bridge contracts (no changes needed)

### Backwards Compatibility
✅ Fully backwards compatible. Existing prompt syntax continues to work:
- `@review provider=cline` — still works
- `@r provider=cline` — still works
- `@review-cline` — still works (parser suffix support)
- `@r-cln` — now works (new combined alias)

---

## Usage Examples

All equivalent:

```
@review provider=cline
@r provider=cline
@review-cline
@r-cline
@r-cln
```

---

## Rollout

No rollout needed. Changes are:
- Config update (auto-loaded at bridge startup)
- Internal hook simplification (same external behavior)

All providers automatically use new aliases through shared parser.

---

## Related Packets

- PKT-PRV-031 — Shared prompt-trigger bridge (uses this config)
- PKT-PRV-033 — Claude Option A (wrapper baseline)
- PKT-PRV-055 — Claude Option B (hooks use config)
- Phase 4.4 — Provider Prompt Tag Surface Integration (precursor)

---

## Notes

- Config can be extended with new tag/provider combos without code review
- Schema validation ensures config integrity
- Documentation in spec provides guidance for future extensions
