# components/source_control/

Source-control dependency and host-integration component.

## Intent

Own access to git and the code forge, plus source-control introspection and bootstrap. Workflow policy (worktree lifecycle, release, ledger) stays with the component that owns it; this component only runs and reports git and forge operations.

## Capabilities

- Detect source-control availability and missing dependencies.
- Install or uninstall declared source-control tool dependencies through shared workflow steps.
- Expose source-control status through MCP and in-process API calls.
- Keep bootstrap/probe logic separate from higher-level release or job orchestration.
- Run the named git operations and forge (GitHub through `gh`) reads and writes that other components need, with typed `EXT-GIT-*` and `EXT-FORGE-*` errors (error kind `source-control`).

## Key Files

- `source_control_api.py` service entrypoint (repository context, dependency status, install).
- `git_api.py` and `forge_api.py` the approved public git and forge operations; each lists its operations in `__all__`. Other components import only these (see the approved cross-component APIs table in `docs/standards/ARCHITECTURE_STANDARDS.md`).
- `git_access.py` and `forge_access.py` the implementation. Internal: `run_git` and the other helpers are not part of the API.
- `source_control_bootstrap.py` dependency declarations and availability checks.
- `probes.py` host detection helpers.
- `source_control_mcp.py` MCP wrapper.
