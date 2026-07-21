# AS19/AS30/AS31 Stage-1 Foundation Contracts — Self-Review

**Date**: 2026-07-20  
**Reviewer**: Claude (T3 self-review)  
**Scope**: New foundation contracts implemented directly (bypassing gateway agents due to repeated TO-AGW-076 timeouts)

## Files Reviewed

1. `src/audiagentic/foundation/transports/harness_status_observer.py` (AS19 Stage-1)
2. `src/audiagentic/foundation/transports/session_binding.py` (AS30 Stage-1)
3. `src/audiagentic/foundation/transports/agent_output.py` (AS31 Stage-1)
4. `src/audiagentic/components/providers/contracts/harness_status_observer.py` (AS19 Stage-2 partial)
5. `src/audiagentic/components/providers/contracts/session_binding.py` (AS30 Stage-2 partial)

## Test Coverage

- `tests/unit/foundation/transports/test_harness_status_observer_contract.py` — 18 tests, all passing
- `tests/unit/foundation/transports/test_agent_output_contract.py` — exists, passes (244 total in suite)

## Critical Findings

### C1: `ResolvedSessionSurface` Naming Collision in `providers/contracts/session_binding.py`

**Location**: `providers/contracts/session_binding.py:33`

The file defines `ResolvedSessionSurface` with 5 fields (provider_id, surface_id, surface_version, identity_context_fingerprint, execution_context_fingerprint, capabilities). This **shadows** the canonical `ResolvedSessionSurface` from `foundation/transports/session_surface.py` (the full AS29 snapshot with ~15+ fields) which is re-exported by `providers/contracts/session_surface.py`.

**Impact**: Any code importing from `providers/contracts/session_binding.py` gets an incompatible `ResolvedSessionSurface` that cannot be substituted for the canonical AS29 surface snapshot. Callers that construct one cannot pass it to resolvers expecting the foundation type.

**Fix**: Rename the type in `providers/contracts/session_binding.py` to `BindingResolutionContext` or remove it and reuse the foundation `ResolvedSessionSurface` from `providers/contracts/session_surface.py`.

### C2: `SessionMappingCapabilities` Duplicated with Divergent Fields

**Locations**:
- `foundation/transports/session_binding.py:91` — authoritative definition, validated with `__post_init__`
- `providers/contracts/session_binding.py:17` — separate definition, different fields

The providers version has `ref_scope` (not in foundation) and is missing `close_session`, `share_existing`, `replace_existing`, `requires_same_project`, `requires_same_execution_context`, `ref_namespace`. The providers version also lacks cross-field validation (open_new ↔ returns_opaque_ref constraint).

**Impact**: Two incompatible `SessionMappingCapabilities` types in the codebase. The AS30 plan explicitly says capabilities come from AS29 resolved surface — the authoritative type is in the foundation, not duplicated in providers contracts.

**Fix**: Remove `SessionMappingCapabilities` from `providers/contracts/session_binding.py`. Import and reuse `SessionMappingCapabilities` from `foundation/transports/session_binding.py` (it's already a foundation-neutral type).

## Warning Findings

### W1: `StatusObserverLease` Import Not Used Correctly in Normalizer

**Location**: `providers/contracts/harness_status_observer.py:109`

`normalize_harness_status_observation` accepts `lease: StatusObserverLease` but never uses `lease.binding_id` in the returned `StatusEvidence`. The `StatusEvidence` correlation_id field is set to `None` explicitly. This is a spec gap — AS19 step 6 says adapters "extract sequence and validate correlation" which implies `binding_id` should be the `correlation_id` in the evidence.

**Fix**: Either pass `lease.binding_id` as `correlation_id` in the returned `StatusEvidence`, or document explicitly why it's omitted (e.g., correlation is set later by the pipeline when consuming the evidence).

### W2: Missing `session_binding.py` in Foundation `__init__` Exports

**Location**: `foundation/transports/__init__.py`

`session_binding.py` defines `BindingRelation`, `SessionOwnership`, `SessionMappingCapability`, `SessionMappingCapabilities`, `ProviderSessionRef`, `SessionBindingIntent` — none are exported from the foundation `__init__`. Callers must import directly from `foundation.transports.session_binding`, but the foundation pattern is to export all public types from `__init__`.

**Fix**: Add the AS30 foundation types to `foundation/transports/__init__.py`.

### W3: `agent_output.py` Error Code Numbering Inconsistency

**Location**: `foundation/transports/agent_output.py:67-86`

The `_validate_id` helper uses hardcoded `number=3` or `4` based on field name string comparison (`if name == "session_id" else 4`). The `observed_at` validation also uses `number=3` (line 173), which would produce a duplicate error code `VAL-OUTPUT-003` for two different validation failures.

**Fix**: Assign unique sequential error numbers. `session_id` → 003, `turn_id` → 004, and `observed_at` → a new 007 (after 006 for UNKNOWN_KIND).

## Info Findings

### I1: `HarnessStatusObserverCapability` Missing from Providers `__init__` `__all__`

**Location**: `providers/contracts/__init__.py:19-34`

`HarnessStatusObserverCapability` is imported at line 3 but not listed in `__all__`. It can be imported but won't be included in `from providers.contracts import *`.

**Fix**: Add to `__all__`.

### I2: `normalize_harness_status_observation` Refines `model-activity` Without Validation

**Location**: `providers/contracts/harness_status_observer.py:138-140`

Status is refined to `f"model-{activity}"` from an `attributes` dict, but there's no validation that the resulting string is a canonical status. If `activity` is `"hacking"`, the evidence would carry `"model-hacking"` which is not in the canonical enum.

**Fix**: Add a whitelist of valid activity suffixes, or validate against a closed set before constructing the composite status.

## Overall Rating: B+

**Architecture**: A — Foundation types are neutral, correct separation of concerns, no agents↔providers leakage.
**Test Coverage**: A — Foundation contracts have comprehensive test suites.
**Implementation Completeness**: B — C1 and C2 are pre-merge blockers; W1–W3 should be addressed.

**Pass/Fail**: FAIL (C1 and C2 must be fixed before `providers/contracts/session_binding.py` can be used safely)

**Rework Required**: Targeted fixes only — no architectural rework needed.

## Fixes Applied (2026-07-20 same session)

| Finding | Status | Change |
|---------|--------|--------|
| C1 | ✅ Fixed | Renamed `ResolvedSessionSurface` → `BindingResolutionContext` in `providers/contracts/session_binding.py`; updated Protocol parameter names |
| C2 | ✅ Fixed | Removed duplicate `SessionMappingCapabilities` from `providers/contracts/session_binding.py`; now imports authoritative type from `foundation.transports.session_binding` |
| W1 | ✅ Fixed | `normalize_harness_status_observation` now passes `lease.binding_id` as `correlation_id` |
| W2 | ✅ Fixed | Added AS30 foundation types to `foundation/transports/__init__.py` |
| W3 | ✅ Fixed | `observed_at` uses `number=7`, `is_final` uses `number=8`; added constants `ERR_OUTPUT_INVALID_OBSERVED_AT` and `ERR_OUTPUT_INVALID_IS_FINAL` |
| I1 | ✅ Fixed | Added `HarnessStatusObserverCapability` to providers contracts `__all__` |
| I2 | Deferred | Whitelist for `model-{activity}` compound statuses — requires AS19 canonical status table, out of scope for Stage-1 |

**Post-fix test result**: 0 regressions. Same 11 pre-existing failures (unrelated to AS19/AS30/AS31 contracts).

---
**Session context**: Stage-2 gateway agents all timed out (TO-AGW-076). Stage-1 direct implementation completed with tests. Self-review applied fixes inline.
