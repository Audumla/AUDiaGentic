# PKT-LFC-013 — Converge fresh-install and release-bootstrap on baseline sync

**Phase:** Phase 1.4  
**Status:** WAITING_ON_DEPENDENCIES  
**Owner:** Lifecycle + Release  
**Scope:** workspace

## Goal

Refactor fresh install and project release bootstrap to use the shared baseline sync engine so clean-project install, existing-project refresh, and self-host bootstrap all apply the same managed baseline contract.

## Dependencies

- `PKT-LFC-012` VERIFIED
- `PKT-RLS-011` VERIFIED

## Expected implementation surface

- `src/audiagentic/lifecycle/fresh_install.py`
- `src/audiagentic/release/bootstrap.py`
- `tests/e2e/lifecycle/test_fresh_install.py`
- `tests/integration/release/test_release_bootstrap.py`
- `tests/integration/test_example_scaffold.py`

## Acceptance criteria

- fresh install no longer relies on a minimal scaffold that omits managed prompt/provider assets
- release bootstrap no longer relies on a separate hard-coded asset copy list
- tests prove the same baseline contract applies in clean-project and self-host flows
