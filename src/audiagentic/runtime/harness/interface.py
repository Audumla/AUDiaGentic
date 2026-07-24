"""Harness module interface contract.

Every harness implementation must be a package at runtime/harness/<type>/ and
expose two submodules — ``install`` and ``runner`` — each providing the
functions listed in the protocols below.

The harness facade (harness/__init__.py) dispatches to these via importlib.
No harness-specific imports are permitted in the facade or this file.

install submodule
-----------------
install_to(target, project_root) -> int
    Verify an installed harness and generate AUDiaGentic configuration.

cleanup_runtime(target) -> int
    Remove AUDiaGentic-generated runtime files. Never remove a user-installed
    harness CLI or user assets (models, logs).

build_runtime_sync(*, reason, component_id, target) -> dict
    Build a structured runtime-sync payload (no I/O).

refresh_harness_config_if_installed(project_root, *, reason, component_id) -> bool
    Regenerate agent config and request runtime reload if harness is present.
    Returns True if the harness was present and the refresh was applied.

refresh_materialized_agent_config(target, project_root) -> int
    Rebuild generated agent config for current project/component state.

request_runtime_reload(project_root, *, reason, component_id) -> Path
    Write a structured runtime-action marker; return the marker path.

runner submodule
----------------
RunnerParams
    Dataclass with fields: prompt, mode, verbose. Same shape across all harnesses.

build_global_context(*, project_root, agent_runtime, enable_mcp) -> context
    Resolve config, start any required backend, return an opaque context object.

run_agent(ctx, params) -> any
    Launch the harness CLI using the resolved context and runner params.

translate_agent_args(params) -> list[str]
    Translate harness-agnostic RunnerParams into harness-specific CLI flags.

env_flag(name, default) -> bool
    Read a boolean from an environment variable.

MCP management
--------------
Two distinct MCP concerns, two distinct mechanisms — do not conflate them:

1. Durable provider-facing config. The harness's matching provider descriptor
   (``config/providers/<id>.yaml``) declares an ``mcp_config`` ManagedConfigSpec
   wired to the provider's ``mcp_format`` module. This is the sole mechanism for
   entries durably added/removed/listed/reloaded in the harness's own native
   config file (e.g. for a user running the CLI standalone, outside AUDiaGentic).
2. Launch-time curated surface. What MCP servers are visible for THIS
   AUDiaGentic-driven launch — see "MCP launch surface" below. Provider-owned,
   mechanism-hidden, requested through ``providers_api``, never a durable file
   write from the harness's own install/runner code.

No harness install or runner module implements its own MCP file management for
either concern — see [CREATING_A_HARNESS.md](../../../../docs/standards/CREATING_A_HARNESS.md).

MCP launch surface
-------------------
A harness that wants launch-time MCP tool-set control (curated vs. whatever the
CLI natively discovers) does NOT implement this itself. Instead:

1. The harness's ``runner`` calls
   ``providers_api.prepare_projected_provider_mcp_surface(...)``. The provider
   component owns management projection policy and delegates neutral descriptor
   collection to ``foundation.mcp.projection`` before invoking the provider
   materializer. Harnesses never duplicate that policy or import an adapter
   module directly (architecture §1).
2. The matching provider adapter package
   (``components/providers/adapters/<id>/mcp_surface.py``) implements
   ``prepare_mcp_surface(request) -> McpLaunchSurfaceResult`` — the ONLY place
   that knows HOW to deliver curated entries for that specific CLI (patched
   flags, an env var, a generated file). Optional: a provider with no such
   module returns ``supported=False`` and callers decide how to proceed.

This split exists because ``runtime.harness`` (runtime orchestration) may
depend on ``components.providers`` via its approved public API, but
``components.providers`` (a platform component) must never depend back on
``runtime.harness`` — see ARCHITECTURE_STANDARDS.md §1's dependency table.

Launch model — intents, not transports (HA04)
---------------------------------------------
A harness's ``runner`` does NOT build its own CLI command/flags/env, and it
never selects a transport. The caller expresses an *intent*; the provider's
builder assembles its richest surface to fulfil it.

Launch INTENTS (caller-facing):
  execute      run one turn and capture a parsed result (the gateway task path)
  interactive  a live session for a human at a terminal
  agent        a live programmatic agent session

For each intent, the provider's adapter owns HOW it is fulfilled — which
transports and channels it uses (native tty/pipe, ACP, RPC hooks, ...). The
caller never names a transport: it says "launch an agent session," and pi's
adapter decides to use ACP for interaction plus native RPC hooks for
observability, because that is pi's richest surface. Transports/channels are a
provider concern; ACP is a transport, never an intent.

Dispatch: ``resolve_launch_builder(provider_id, intent)`` (services/execution)
resolves the builder — a hand-written ``adapters/<id>/<submodule>`` builder
(the escape hatch for genuinely custom spec construction) wins; otherwise the
declarative recipe block of the same name builds a ``ProviderLaunch`` via
``build_launch_spec`` (execute via the descriptor ``execution:`` runner). Every
builder returns the one ``ProviderLaunch(executable, args, environment)`` shape,
which the intent's spawn strategy consumes (execute -> pipe+parse; interactive
-> supervised tty; agent -> the ACP transport).

Capability: a provider descriptor declares ``launches`` = {intent: {interaction:
[...], observability: [...]}} — a queryable, role-based channel surface
(surfaced in ``describe_provider``). It gates support (undeclared intent =
unsupported; declared-but-no-builder = fail closed) and lets callers introspect
or request a constrained subset, while the default is the harness's fullest
surface.

A harness's ``runner`` contains no per-provider CLI-flag logic — only the
generic lifecycle (context, MCP-surface request, logging, startup info, process
supervision). AUDiaGentic does not customise the harness for interactive use
(no injected extensions/UI); only the MCP surface's adapter is added at launch,
solely to deliver AG's projected MCP servers.
"""
