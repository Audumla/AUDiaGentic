# Phase 0.3 Execution Guardrails

## Purpose

This addendum makes three Phase 0.3 execution rules explicit so the repository refactor can be executed without case-by-case interpretation drift:

- compatibility shim implementation pattern
- per-slice expected outcome baselines
- terminology ambiguity capture during inventory

This document should be read alongside:
- `49_Repository_Domain_Refactor_and_Package_Realignment.md`
- `57_Phase_0_3_Repository_Domain_Refactor_and_Package_Realignment.md`
- `PKT-FND-010`
- `PKT-FND-011`
- `PKT-FND-012`
- `PKT-FND-013`

## 1. Compatibility shim implementation pattern

For this checkpoint, the canonical shim strategy is:

- keep the old import path in place only as a forwarding shim
- the shim re-exports symbols from the new canonical module location
- the shim may emit a `DeprecationWarning`
- the shim must not contain new business logic
- the shim must not become a second live implementation root

Preferred pattern:

```python
# PHASE-0.3-COMPAT-SHIM
from audiagentic.new.path import *  # noqa: F401,F403

import warnings
warnings.warn(
    "Legacy import path is deprecated; use audiagentic.new.path",
    DeprecationWarning,
    stacklevel=2,
)
```

Operational rules:
- `find_legacy_paths.py` must treat files explicitly marked as `PHASE-0.3-COMPAT-SHIM` as approved temporary shim locations, not as unresolved stale code
- `inventory_imports.py` may still report shimmed legacy paths, but they should be identifiable as shim-covered
- all shimmed paths remain subject to removal in `PKT-FND-013` unless explicitly extended by the migration map

## 2. Per-slice expected outcome baselines for PKT-FND-012

The support scripts are the mechanism. The expected baselines below define the success condition.

### Slice 12A — target scaffolding and shim placeholders

Expected state:
- target directories exist
- shim placeholder paths exist where required by the migration map
- no business logic has moved yet
- import smoke is unchanged from pre-slice baseline

### Slice 12B — contracts/core/config moves

Expected state:
- moved modules live in frozen target locations
- no new forbidden dependency edges are introduced
- public legacy imports for moved modules resolve through approved shims
- legacy paths may remain, but only as approved shims or untouched not-yet-moved areas
- moved modules themselves should not still import from their own legacy locations

### Slice 12C — lifecycle/release shared internals

Expected state:
- lifecycle/release internals moved per migration map
- baseline asset checks still pass
- release/bootstrap path assumptions still resolve
- no new forbidden dependency edges are introduced
- legacy paths in moved lifecycle/release modules are reduced to approved shims only

### Slice 12D — execution/runtime seams

Expected state:
- execution/runtime moves match the frozen target tree
- prompt bridge / launch imports still resolve
- runtime persistence concerns are not leaking back into channels
- no new forbidden dependency edges are introduced
- legacy paths in moved execution/runtime modules are reduced to approved shims only

### Slice 12E — channels/streaming/observability

Expected state:
- channel, stream, and observability moves match the frozen target tree
- formatting/control/telemetry boundaries are preserved
- docs/tests/build references for moved modules are updated
- no new forbidden dependency edges are introduced
- legacy paths in moved channel/stream/observability modules are reduced to approved shims only

## 3. Terminology ambiguity capture during PKT-FND-010

Phase 0.3 does not require bulk renaming, but it does require ambiguity capture so later cleanup is grounded.

`PKT-FND-010` must therefore record terminology ambiguity findings in the ambiguity report.

At minimum, capture:
- current term in use
- file/module/path where it appears
- competing or overlapping term
- why the meaning is blurred
- whether it affects structure now or can wait
- recommended follow-up packet or document

Priority terms to watch:
- Request
- Scope
- Plan
- Task
- WorkPackage
- Job
- Run
- Agent
- Session
- Thread
- Artifact
- Event

Rule for this tranche:
- capture terminology ambiguity during inventory
- do not perform broad terminology rewrites unless a moved file must be touched anyway or the freeze packet explicitly approves a bounded cleanup
