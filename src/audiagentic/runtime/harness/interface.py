"""Harness module interface contract.

Every harness implementation must be a package at runtime/harness/<type>/ and
expose two submodules — ``install`` and ``runner`` — each providing the
functions listed in the protocols below.

The harness facade (harness/__init__.py) dispatches to these via importlib.
No harness-specific imports are permitted in the facade or this file.

install submodule
-----------------
install_to(target, project_root) -> int
    Install the harness CLI and generate agent config under target/.

uninstall_from(target) -> int
    Remove CLI and generated config. Leave user assets (models, logs) intact.

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
Each harness must register a ProviderDescriptor with provider_id
"audiagentic-harness" (or a harness-specific id) that includes a McpConfigSpec
wired to the harness-specific mcp_format module. This is the sole mechanism
through which MCP entries are added, removed, listed, and reloaded for the
harness — no harness install module should implement its own MCP management.
"""
