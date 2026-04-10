# PKT-DIS-001 — Locator provider contract and static registry provider

**Phase:** Phase 8

## Goal
Implement the discovery/registration provider contract and the first static registry backend.

## Dependencies
- Phase 7 VERIFIED
- `40_Discovery_Registration_and_Locator_Provider_Extension.md`

## Ownership boundary
- `src/audiagentic/discovery/contracts.py`
- `src/audiagentic/discovery/static_registry.py`
- `tests/unit/discovery/test_static_registry.py`

## Acceptance
- static registry can register, resolve, list, and expire nodes deterministically
- node-only operation still works when locator provider is disabled
