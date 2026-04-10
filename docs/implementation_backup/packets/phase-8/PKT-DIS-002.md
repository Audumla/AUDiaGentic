# PKT-DIS-002 — Zeroconf locator provider (optional)

**Phase:** Phase 8.1

## Goal
Add optional same-subnet auto-discovery using a zeroconf provider.

## Dependencies
- `PKT-DIS-001`
- explicit operator opt-in

## Ownership boundary
- `src/audiagentic/discovery/providers/zeroconf_provider.py`
- `tests/integration/discovery/test_zeroconf_provider.py`

## Acceptance
- opt-in only
- graceful fallback when multicast discovery is unavailable
- no baseline dependency on zeroconf package
