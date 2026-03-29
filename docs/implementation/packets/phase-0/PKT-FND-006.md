# PKT-FND-006 — Error envelope and error code registry

**Phase:** Phase 0  
**Primary owner group:** Contracts

## Goal

Define and implement the common error envelope and error-code registry used by all CLI and script surfaces.

## Dependencies

- `PKT-FND-002`

## Ownership boundary

Owns:
- `src/audiagentic/contracts/errors.py`
- `docs/specifications/architecture/20_Error_Envelope_and_Error_Codes.md`
- `docs/examples/fixtures/error-envelope.valid.json`
- `docs/examples/fixtures/error-envelope.invalid.json`
- `tests/unit/contracts/test_error_envelope.py`

## Detailed build steps

1. Implement typed error classes by module prefix.
2. Implement `ErrorEnvelope` serializer for JSON mode.
3. Create the initial code registry with reserved prefixes.
4. Add valid/invalid fixtures and schema validation.
5. Add tests proving stable JSON output for representative failures.

## Pseudocode

```python
def to_error_envelope(err):
    return {
        "contract-version": "v1",
        "ok": False,
        "error-code": err.code,
        "error-kind": err.kind,
        "message": err.message,
        "details": err.details or {}
    }
```

## Acceptance criteria

- all CLI/script packets can reference one shared error contract
- valid and invalid fixtures pass/fail as expected
- code registry is documented and frozen for v1
