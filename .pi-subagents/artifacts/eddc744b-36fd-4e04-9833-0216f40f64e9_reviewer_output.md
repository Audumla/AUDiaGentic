## Review Findings

### 1. Correctness and Regressions

**Correct:**
- Foundation neutral transport contract (`foundation/transports/agent_session.py`) properly defines frozen dataclasses, enum validation, scalar-only discipline, and rejects raw/native attributes like `provider_session_ref`, `prompt`, `output`, `tool_arguments`, `payload`. The closed-set `TransportObservationKind` with `TRANSPORT_UNKNOWN` as the bounded unknown state is correct.
- ACP adapter wrapper (`foundation/transports/acp.py`) correctly maps ACP events to `TransportObservation` and maintains the private boundary - `AcpAgentSessionTransport` is not exported from `transports.__all__`, only accessible via direct import from `acp.py`.
- Control payload validation in `SessionControlRequest` properly implements default-deny: only canonical keys are allowed per action (`permission` for `RESPOND_PERMISSION`, `steer_text` for `STEER_TURN`), and no-payload actions (`CANCEL_TURN`, `INTERRUPT_TURN`, `CLOSE_SESSION`) reject any payload.

**Fixed/Issue Found:**
- In `session_surface_resolution.py` line ~250, the `_enforce_validation_ceiling` function has a nested condition that is slightly redundant:
```python
def _enforce_validation_ceiling(
    effective_level: EffectiveObservationLevel,
    validation_state: SurfaceValidationState,
) -> tuple[bool, str]:
    if effective_level.numeric >= 2 and validation_state != SurfaceValidationState.BLOCKED:
        if validation_state != SurfaceValidationState.VALIDATED:
            return True, "unvalidated-high-level"
    return False, ""
```
The outer check `validation_state != SurfaceValidationState.BLOCKED` and inner check `validation_state != SurfaceValidationState.VALIDATED` can be simplified to:
```python
if effective_level.numeric >= 2 and validation_state not in (SurfaceValidationState.BLOCKED, SurfaceValidationState.VALIDATED):
    return True, "unvalidated-high-level"
```

**Note/Risk:**
- The `session_surface_resolution.py` `_probe_installed_version` function relies on `cli_probe` from the descriptor, but this is best-effort and may return `None`. The fallback to using declaration's version constraint is correct per the AS29 spec.

### 2. Tests and Validation

**Correct:**
- `tests/unit/foundation/transports/test_agent_session.py` provides comprehensive tests for frozen/immutable values, enum validation, scalar-only discipline, raw/native data rejection, bounded unknown-kind containment, control payload default-deny, import boundary enforcement, protocol conformance with a fake transport.
- `tests/unit/foundation/transports/test_session_surface.py` tests frozen/immutable values, enum/value validation, scalar-only discipline, and import neutrality for the session-surface module.
- `tests/unit/foundation/transports/test_acp_agent_session_transport.py` provides ACP adapter wrapper tests covering raw-event redaction, known/unknown kind mapping, request correlation, callback exception isolation, cancellation dispositions, no native leakage, protocol conformance, and existing ACP regression parity.

**Correct:**
- The import boundary test in `TestImportBoundary.test_no_components_imports` correctly verifies that `agent_session.py` does not import any `components.*` modules.
- The test `TestAcpAgentSessionTransportExportBoundary` correctly verifies that `AcpAgentSessionTransport` is absent from `transports.__all__` but still accessible via direct import from `acp.py`.

### 3. Simplicity and Maintainability

**Note:**
- The `session_surface_resolution.py` file has extensive internal helper functions for version parsing (`_parse_version`, `_version_satisfies`), platform detection (`_detect_platform_triple`), declaration selection (`_select_declaration`), and adapter existence checking (`_adapter_factory_exists`). This is well-organized but adds complexity. The code follows the AS29 specification correctly with 8 distinct resolution rules.
- The ACP adapter wrapper `acp.py` is large (over 800 lines) but contains both the legacy `AcpSessionTransport` and the new `AcpAgentSessionTransport`. This is intentional for the migration path per AS28 step 13 ("two-commit-compatible migration, not permanent compatibility shims").
- The re-export of `SessionControlAction` from `session_surface.py` to maintain backward compatibility with AS29 surface resolution is correctly documented and implemented:
```python
# Re-export canonical control action from agent_session (AS28 stage 1).
# session_surface uses this for ResolvedSessionSurface.controls; the
# type-only reference avoids duplication while keeping backward-compatible
# imports for provider-side consumers.
from .agent_session import SessionControlAction
```

## Acceptance Report