# PKT-FND-007 — CI validators and packet dependency validation

**Phase:** Phase 0  
**Primary owner group:** Contracts

## Goal

Implement the validator entry points needed to enforce schemas, naming, and packet readiness in CI.

## Dependencies

- `PKT-FND-001`
- `PKT-FND-002`
- `PKT-FND-006`

## Ownership boundary

Owns:
- `tools/validate_schemas.py`
- `tools/validate_packet_dependencies.py`
- `.github/workflows/ci-contracts.yml`
- `tests/integration/contracts/test_ci_validators.py`

## Detailed build steps

1. Implement schema validator entry point.
2. Implement packet dependency graph validator.
3. Add CI workflow job that runs contract validators.
4. Add a smoke integration test proving the tools return non-zero on bad fixtures.

## Pseudocode

```python
def main():
    run_schema_validation()
    run_id_validation()
    run_packet_dependency_validation()
```

## Acceptance criteria

- CI fails on invalid schema fixture
- CI fails on unknown packet dependency
- CI fails on naming drift
- CI succeeds on the known-good baseline
