# Target Codebase Tree

## Frozen Phase 0.3 target shape

```text
src/
  audiagentic/
    contracts/
      canonical_ids.py
      schemas.py
      validation.py
      glossary.py
    core/
    config/
    scoping/
    execution/
      jobs/
      providers/
    runtime/
      lifecycle/
      release/
      state/
    channels/
      cli/
      discord/
      server/
    streaming/
    observability/
    nodes/
      identity.py
      heartbeat.py
      ownership.py
      runtime_state.py
      status.py
      registry.py
      api.py
    discovery/
      registry.py
      locator.py
      providers/
        static.py
        zeroconf.py
        external.py
    federation/
      events.py
      control.py
      transport.py
    connectors/
      external_tasks.py
      tool_registry.py
      sync.py
tools/
  validate_ids.py
  validate_schemas.py
  validate_packet_dependencies.py
  seed_example_project.py
  lifecycle_stub.py
  refresh_model_catalog.py
tests/
  fixtures/
  unit/
  integration/
  e2e/
```

## Phase 0.3 mapping notes

This file now describes the **post-refactor target structure** that `PKT-FND-011` must freeze before `PKT-FND-012` begins.

Interpretation rules for this tranche:

- `execution/` is the home of job orchestration and provider execution behavior.
- `runtime/` is the home of lifecycle, release, and durable runtime/project state concerns.
- `channels/` is the home of human-facing entry or interaction surfaces such as CLI, Discord, and optional server adapters.
- `streaming/` is reserved for live input/output flow and stream-bridging behavior.
- `observability/` is reserved for telemetry, diagnostics, reporting, and later monitoring surfaces.
- `nodes/`, `discovery/`, `federation/`, and `connectors/` remain reserved extension roots during this tranche and are **not** folded into the baseline repository-domain tree.

## Post-checkpoint cleanup rule

The legacy compatibility roots used during `PKT-FND-012` have now been retired. The canonical tree above is the only live production package layout for current work.

Removed legacy roots:

- `src/audiagentic/cli/`
- `src/audiagentic/lifecycle/`
- `src/audiagentic/release/`
- `src/audiagentic/jobs/`
- `src/audiagentic/providers/`
- `src/audiagentic/server/`
- `src/audiagentic/overlay/`

Future packets and docs should reference the canonical domain paths directly.

## Rules

- All production code lives under `src/audiagentic/`.
- All standalone deterministic utility entry points live under `tools/`, but should call library code under `src/audiagentic/`.
- Tests remain centralized under `tests/` and should mirror the frozen domain structure where practical.
- Packets must not create alternative parallel module trees outside the frozen target shape.
- When a packet needs a new module outside this tree, it must update this file before code is written.
- `nodes/`, `discovery/`, `federation/`, and `connectors/` remain optional extension roots and must not become baseline prerequisites during this tranche.

## Future extension note

The later extension line still uses the reserved roots above:

- `src/audiagentic/nodes/`
- `src/audiagentic/discovery/`
- `src/audiagentic/federation/`
- `src/audiagentic/connectors/`

Those roots are intentionally preserved now so future implementation does not need another structural rename just to begin.
