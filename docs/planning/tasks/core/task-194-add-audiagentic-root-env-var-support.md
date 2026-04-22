---
id: task-194
label: Add AUDIAGENTIC_ROOT env var support
state: done
summary: Add AUDIAGENTIC_ROOT env var support to MCP server _bootstrap_repo_root()
spec_ref: spec-6
---











# Description

Add explicit `AUDIAGENTIC_ROOT` support to the planning MCP bootstrap path so isolated mutation tests can target a seeded temp project instead of the real repository.

# Acceptance Criteria

1. MCP bootstrap honors `AUDIAGENTIC_ROOT` when present
2. Isolated MCP mutation tests can run against a temp project root
3. Normal repo auto-detection still works when the env var is absent

# Notes

- Still open: the xfailed isolation class in `tests/integration/planning/test_mcp_tool_calls.py` documents this gap directly

# State

done
