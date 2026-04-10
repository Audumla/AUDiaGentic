# Tools Directory

Organized utility scripts and tools for AUDiaGentic.

## Structure

```
tools/
├── bridges/          # Prompt trigger bridges for various providers
├── checks/           # Validation and analysis tools
├── mcp/              # MCP (Model Context Protocol) servers
│   └── audiagentic-planning/  # AUDiaGentic planning MCP server
├── misc/             # Miscellaneous utilities
├── planning/         # Planning component tools (tm CLI, helpers)
└── validation/       # Schema and data validation tools
```

## Subdirectories

### `bridges/`
Prompt trigger bridge implementations for different AI providers:
- `prompt_trigger_bridge.py` - Base bridge implementation
- `*_prompt_trigger_bridge.py` - Provider-specific bridges (claude, codex, gemini, etc.)

### `checks/`
Analysis and validation utilities:
- `check_baseline_assets.py` - Verify baseline assets
- `check_cross_domain_imports.py` - Detect cross-domain import issues
- `find_legacy_paths.py` - Find legacy file paths

### `mcp/`
MCP servers for AI agent integration:
- `audiagentic-planning/` - AUDiaGentic planning MCP server
  - `audiagentic-planning_mcp.py` - Main MCP server
  - `MCP_README.md` - MCP setup documentation

### `misc/`
Miscellaneous utilities:
- `claude_hooks.py` - Claude-specific hooks
- `create_sandbox.py` - Sandbox environment creation
- `inventory_imports.py` - Import inventory analysis
- `lifecycle_stub.py` - Lifecycle management stub
- `provider_status.py` - Provider status reporting
- `refactor_smoke.py` - Refactoring smoke tests
- `refresh_model_catalog.py` - Model catalog refresh
- `regenerate_tag_surfaces.py` - Tag surface regeneration
- `seed_example_project.py` - Example project seeding

### `planning/`
Planning component tools:
- `tm.py` - Task manager CLI
- `tm_helper.py` - Python helper for programmatic access

### `validation/`
Schema and data validation:
- `validate_ids.py` - ID validation
- `validate_packet_dependencies.py` - Packet dependency validation
- `validate_schemas.py` - JSON schema validation

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

## Adding New Tools

1. Place the tool in the appropriate subdirectory
2. Make it executable if it's a CLI tool (`chmod +x tool.py`)
3. Add documentation to this README
4. If it's an MCP server, add it to `tools/mcp/` and update `MCP_README.md`
