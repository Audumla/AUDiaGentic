# src/audiagentic/

Primary Python package for AUDiaGentic.

## Intent

This package is split by responsibility, not by feature flag:

- `components/` exposes installable product-facing capabilities such as session control, provider integration, release tooling, and job orchestration.
- `foundation/` provides reusable primitives: component metadata, contracts, events, logging, MCP helpers, workflow engines, and host probes.
- `runtime/` owns mutable runtime concerns: layered config loading, harness materialization, rig lifecycle, install/update flows, and durable state.
- `config/` ships package-default YAML and skill/config assets that `foundation` and `runtime` load at install time and during execution.

## Read This First

Agents usually orient fastest in this order:

1. `components/` to find user-visible behavior.
2. `runtime/` to see how behavior is configured and persisted.
3. `foundation/` to understand shared contracts and infrastructure.
4. `config/` to inspect packaged defaults that shape installed projects.
