# External access to local MCP component tools

AUDiaGentic exposes its registered local MCP servers through one generic,
project-scoped CLI accessor. This supports scripts or remote shell agents that
cannot discover native provider MCP tools. **Planning and Ledger rules remain
inside their existing components**; callers do not manipulate Markdown or
ledger JSON directly.

## CLI

```sh
audiagentic mcp call ag-planning plan_get_item \
  arguments '{"item_id":"EX01"}' project /path/to/isolated-project-worktree

audiagentic mcp call ag-planning plan_create_item \
  arguments-file /path/to/create-item.json project /path/to/isolated-project-worktree

audiagentic mcp call ag-ledger get_pending_events \
  arguments '{"group_by":"flat"}' project /path/to/isolated-project-worktree

audiagentic mcp call ag-ledger record_change_event \
  arguments-file /path/to/change-event.json project /path/to/isolated-project-worktree
```

The supplied JSON object is **the existing MCP tool's arguments**, not the
domain Python function's positional arguments. For example
`plan_create_item` expects `{"item": {"plan": "...", "title": "..."}}`
and `record_change_event` expects `{"event": { ... }}`.
Use `audiagentic mcp ag-planning help` and the canonical tool schemas as
the contract. An arguments file is limited to 1 MiB. If no arguments are
needed, omit the `arguments` clause.

The explicit `project PATH` is mandatory for reads as well as writes.
The CLI starts **the locally declared server**, configured to use precisely
that root, over stdio and returns JSON on stdout. It uses the same Pydantic
schema validation, planning workflows, identity integrity checks and ledger
write-once rules as an MCP-capable agent. MCP tool errors produce a nonzero
exit code, not a successful error-shaped result. An external/HTTP-only
server cannot be launched by this local command.

This does not install the server into the caller's harness and does not
open a network listener. It does not add Planning or Ledger code to the
target project: their documents stay in that project's own directories.
Commit the generated Planning/Review/Ledger records on the target project's
task branch and use its ordinary review/merge process.

## Repairing a verified duplicate identity

When the **same** item ID exists in active and completed Planning records,
ordinary item lookup/update fails closed. Use the narrowly scoped repair
only after verifying both copies and choosing a globally unused replacement:

```sh
audiagentic mcp call ag-planning plan_rekey_duplicate_active_item \
  arguments '{"plan":"run-example","item_id":"ABC07","new_item_id":"ABC16"}' \
  project /path/to/isolated-project-worktree
```

This tool requires exactly one active and one terminal copy in the same plan,
rejects linked reviews or an occupied replacement ID, and moves only the
active copy via the recoverable Planning transaction. The terminal copy is
unchanged, while the active item retains its content and pending state with
an explicit identity-reconciliation entry. This is not a general-purpose
rename or a completion shortcut.

## Python

The same external accessor is available to Python automation:

```python
from pathlib import Path
from audiagentic.components.project import project_api

project_root = Path("/path/to/isolated-project-worktree")
result = project_api.call_mcp_tool(
    project_root, "ag-planning", "plan_get_item", {"item_id": "EX01"}
)
```

For a long-lived script performing many calls, use the official MCP Python
`ClientSession` and `stdio_client` with
`audiagentic.components.planning.planning_mcp` or
`audiagentic.components.ledger.ledger_mcp`, setting
`AUDIAGENTIC_REPO_ROOT` to the explicit task worktree. This avoids spawning
a new subprocess per call while retaining all canonical validation.

Avoid direct writes to the plan file store or per-event ledger files.
Direct `planning_api` / `ledger_api` calls are for trusted in-process
component integrations; they do not include the MCP tool boundary.
