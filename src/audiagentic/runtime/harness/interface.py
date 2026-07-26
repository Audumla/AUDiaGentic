"""Harness module interface contract.

"Harness" is not a closed, hardcoded pair (pi, opencode) — it is a capability
a provider either has or doesn't. Any provider that declares sufficient
launch capability (``launches: {interactive: {...}, agent: {...}}``, HA04)
and a materialize capability (HA07) can serve as an AG CLI backend. Pi and
OpenCode are simply the two providers that currently clear that bar, not a
architectural limit — broadening ACP to more providers (HA06, currently
blocked on the AS19 foundation) directly grows the set of usable harnesses,
with zero new runtime code, once the requirement below is fully retired.

CURRENT (transitional) implementation shape: every harness implementation is
still a package at runtime/harness/<type>/ exposing two submodules —
``install`` and ``runner`` — each providing the functions listed in the
protocols below. ``get_harness_type()``'s config resolution is already fully
open (any string, config-driven, no hardcoded list) — the ``_mod()``
dispatcher immediately below it is what still requires a bespoke Python
package per type via ``importlib``. That requirement is transitional debt,
not permanent architecture: once HA07's materialize deep-cut and HA06's ACP
broadening both land, install/runner become generic orchestration
parametrized by ``provider_id``, and a new AG-CLI-capable provider needs only
a capability declaration in its own descriptor YAML, not a new
runtime/harness/<type>/ package. Do not add new harness-specific code to this
package on the assumption that "harness" means "pi or opencode" — write it as
provider-capability-driven from the start wherever possible, even before the
full generalization lands.

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

Launch model — named profiles, not transports (HA04)
-----------------------------------------------------
A harness's ``runner`` does NOT build its own CLI command/flags/env, and it
never selects a transport. The caller expresses a *launch profile by name*;
the provider's builder assembles its richest surface to fulfil it.

Launch profiles are open-ended, not a closed enum — there is no fixed
registry of valid names to validate against, and no "unknown profile" error.
Three exist today (each with its own dedicated caller that selects it by
name, never enumerated centrally):
  execute      run one turn and capture a parsed result (the gateway task
               path — ``execute_provider``; a full runner, not just a
               spec-builder, so it has its own dedicated entry point and is
               reachable via the dispatch below mainly for introspection)
  interactive  a live session for a human at a terminal (the AG TUI launcher)
  agent        a live programmatic agent session (the gateway's ACP session
               path, which then hands the launch to ``SessionRuntime`` —
               session lifecycle, e.g. one-shot vs. ongoing, is
               ``SessionRuntime``'s concern, not the launch mechanism's)

Adding a new profile needs no registry edit: drop a hand-written
``adapters/<id>/<name>.py::build_launch`` (the escape hatch), or a matching
declarative recipe block, and declare it in the provider's ``launches``
capability. For each profile, the provider's adapter owns HOW it is
fulfilled — which transports and channels it uses (native tty/pipe, ACP, RPC
hooks, ...). The caller never names a transport: it says "launch an agent
session," and pi's adapter decides to use ACP for interaction plus native RPC
hooks for observability, because that is pi's richest surface.
Transports/channels are a provider concern; ACP is a transport, never a
profile name.

Dispatch: ``resolve_launch_builder(provider_id, name)`` (services/execution)
resolves the builder — a hand-written ``adapters/<id>/<submodule>`` builder
(the escape hatch for genuinely custom spec construction) wins; otherwise the
declarative recipe block of the same key builds a ``ProviderLaunch`` via
``build_launch_spec``. "interactive"/"agent" resolve through a small legacy
submodule/key mapping (their builder file/recipe key predates this
convention — "agent" is built via the "acp" submodule, since ACP is the
transport, not the caller-facing name); any other profile name is tried
directly by convention (submodule name = profile name). Every builder returns
the one ``ProviderLaunch(executable, args, environment)`` shape, which the
profile's spawn strategy consumes (execute -> pipe+parse; interactive ->
supervised tty; agent -> the ACP transport).

Capability: a provider descriptor declares ``launches`` = {name: {interaction:
[...], observability: [...]}} — a queryable, role-based channel surface
(surfaced in ``describe_provider``). It gates support (undeclared name =
unsupported, None, no error; declared-but-no-builder = fail closed) and lets
callers introspect or request a constrained subset, while the default is the
harness's fullest surface.

A harness's ``runner`` contains no per-provider CLI-flag logic — only the
generic lifecycle (context, MCP-surface request, logging, startup info, process
supervision). AUDiaGentic does not customise the harness for interactive use
(no injected extensions/UI); only the MCP surface's adapter is added at launch,
solely to deliver AG's projected MCP servers.
"""
