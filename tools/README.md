# Tools Directory

Organized utility scripts and tools for AUDiaGentic.

## Structure

```
tools/
├── lib/              # Shared helpers imported by other tool scripts
├── bridges/          # Prompt trigger bridges for various providers
├── checks/           # Structural integrity and cross-domain analysis
├── mcp/              # MCP (Model Context Protocol) servers
│   └── audiagentic-planning/  # AUDiaGentic planning MCP server
├── misc/             # Miscellaneous development utilities
├── planning/         # Planning component CLI (tm) and helpers
└── validation/       # Schema and data validation scripts
```

## Subdirectories

### `lib/`

Shared Python helpers imported by other tool scripts. Not standalone tools.

- `repo_paths.py` — Multi-fallback repository root discovery. Provides `REPO_ROOT`, `SRC_ROOT`, `TOOLS_ROOT`, `DOCS_ROOT`. All tool scripts should bootstrap with this rather than using `parents[N]` depth counting. Fallback chain: `AUDIAGENTIC_REPO_ROOT` env var → `.git` directory walk → `pyproject.toml` walk → structural sentinel (`src/audiagentic` + `tools`).

### `bridges/`

Prompt trigger bridge scripts — one per supported AI provider. Each bridge receives a raw prompt from stdin (or file), normalizes it, and forwards it to the appropriate provider using the shared launch grammar.

- `prompt_trigger_bridge.py` — Base bridge (dispatches to provider-specific bridges)
- `claude_prompt_trigger_bridge.py`, `codex_prompt_trigger_bridge.py`, etc. — Provider-specific wrappers

All bridges import from `execution.jobs.prompt_trigger_bridge` (not moved in v3).

### `checks/`

Read-only structural integrity and analysis scripts. Safe to run at any time — no writes.

- `check_baseline_assets.py` — Verify that required baseline assets exist in `.audiagentic/`
- `check_cross_domain_imports.py` — Detect imports that cross domain boundaries per v3 dependency rules; reports violations
- `find_legacy_paths.py` — Search for import paths that refer to pre-v3 module locations (moved roots such as the old contracts, config, streaming, and execution/providers paths)
- `repair_broken_refs.py` — Find and repair broken references in planning documents. By default only checks metadata fields (YAML frontmatter) to avoid false positives from historical body text references. See `docs/planning/docs/BROKEN_REFERENCE_POLICY.md` for details.

### `mcp/`

MCP (Model Context Protocol) server implementations for AI agent integration.

- `audiagentic-planning/audiagentic-planning_mcp.py` — MCP server exposing planning operations (`tm_*` tools) to Claude and other MCP-capable agents
- `audiagentic-planning/MCP_README.md` — Provider configuration and setup instructions

### `misc/`

Development utilities that do not fit a narrower bucket.

- `claude_hooks.py` — Executed by Claude Code hooks (`UserPromptSubmit`, `PreToolUse`); routes canonical tags through the bridge
- `cleanup_test_artifacts.py` — Remove test artifacts (files with `test-` prefix) and optionally reset ID counters
- `create_sandbox.py` — Spin up an isolated sandbox project for manual testing
- `inventory_imports.py` — Audit all imports across `src/` and report domain breakdown
- `lifecycle_stub.py` — Stub lifecycle operations for development without a live project
- `provider_status.py` — Report live provider connectivity and model availability
- `refactor_smoke.py` — Quick smoke test of all v3 import paths; run after structural changes
- `refresh_model_catalog.py` — Pull latest model metadata from provider APIs and update `foundation/config/`
- `regenerate_tag_surfaces.py` — Rebuild the provider tag surface files under `interoperability/providers/surfaces/`
- `seed_example_project.py` — Initialize an example `.audiagentic/` project structure

### `planning/`

Command-line interface for the planning subsystem. Used by humans and CI.

- `tm.py` — Full-featured task manager CLI; wraps `planning.app.api.PlanningAPI`
- `tm_helper.py` — Thin Python API wrapper for programmatic use from other scripts or notebooks

### `validation/`

Data and schema validation scripts. Run in CI or before merging.

- `validate_ids.py` — Check all planning item IDs for format correctness and uniqueness
- `validate_packet_dependencies.py` — Verify that declared inter-item dependencies resolve to real items
- `validate_schemas.py` — Load and validate all JSON schemas in `foundation/contracts/schemas/`

## Usage

### MCP Server (Recommended for AI Agents)

```bash
# Start the MCP server (for provider integration)
python tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py
```

See `tools/mcp/MCP_README.md` for provider configuration.

### Planning CLI

```bash
# Create a new task
python tools/planning/tm.py new task --label "My Task" --summary "Description" --spec spec-0001

# Get next available tasks
python tools/planning/tm.py next task --domain core

# Validate all planning objects
python tools/planning/tm.py validate
```

### Python Helper

```python
import tools.planning.tm_helper as tm

# Create a task
result = tm.new_task("Label", "Summary", spec="spec-0001", domain="core")

# Get status
status = tm.status()
```

### Cleanup Test Artifacts

```bash
# Dry run: see what would be removed
python tools/cleanup_test_artifacts.py --dry-run

# Remove test artifacts (files with test- prefix)
python tools/cleanup_test_artifacts.py

# Remove test artifacts and reset ID counters
python tools/cleanup_test_artifacts.py --reset-counters
```

This tool helps prevent ID counter inflation from test artifacts. Test artifacts should use the `test-` prefix convention (e.g., `test-task-0001.md`) to be identified for cleanup.

## Adding New Tools

1. Place the tool in the appropriate subdirectory
2. Make it executable if it's a CLI tool (`chmod +x tool.py`)
3. Add documentation to this README
4. If it's an MCP server, add it to `tools/mcp/` and update `MCP_README.md`
