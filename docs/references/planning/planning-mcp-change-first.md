# MCP Change First

This document should be read and applied **before** the rest of this pack.

## Why this change comes first

The current `planning-module-implementation` branch exposes `workflow` on the planning MCP create tools for tasks and work packages, but the live helper layer does not currently accept that argument.

That means an MCP client can call:

- `tm_new_task(..., workflow="review_heavy")`
- `tm_new_wp(..., workflow="standard")`

but the helper signatures in `tools/planning/tm_helper.py` can still reject those calls if they are not updated first.

This is a concrete runtime mismatch, not just a documentation problem.

## Required first fixes

Update `tools/planning/tm_helper.py` so it handles both of the current helper/runtime mismatches:

1. MCP/helper `workflow` passthrough alignment
2. profile-pack YAML top-level shape alignment

The helper must match the MCP surface and pass `workflow` through to `PlanningAPI.new()`.

### `new_task()`

Change from:

```python
def new_task(label: str, summary: str, spec: str, domain: str = "core", target: str | None = None, parent: str | None = None) -> dict[str, Any]:
```

to:

```python
def new_task(
    label: str,
    summary: str,
    spec: str,
    domain: str = "core",
    target: str | None = None,
    parent: str | None = None,
    workflow: str | None = None,
) -> dict[str, Any]:
    item = _api.new(
        "task",
        label=label,
        summary=summary,
        spec=spec,
        domain=domain,
        target=target,
        parent=parent,
        workflow=workflow,
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}
```

### `new_wp()`

Change from:

```python
def new_wp(label: str, summary: str, plan: str, domain: str = "core") -> dict[str, Any]:
```

to:

```python
def new_wp(
    label: str,
    summary: str,
    plan: str,
    domain: str = "core",
    workflow: str | None = None,
) -> dict[str, Any]:
    item = _api.new(
        "wp",
        label=label,
        summary=summary,
        plan=plan,
        domain=domain,
        workflow=workflow,
    )
    return {"id": item.data["id"], "path": str(item.path.relative_to(_ROOT))}
```

## What this unlocks

Once this mismatch is fixed, the rest of the pack can be reviewed and applied with much lower risk because:

- MCP create flows align with helper behavior
- workflow overrides can be exercised through MCP
- later documentation-surface and profile work is not blocked by a basic signature bug

## Scope of this first fix

This doc covers the two concrete helper/runtime mismatches that should be fixed before applying the wider overlay.

It does **not** by itself make the whole pack merge-ready. It is the first implementation step that should happen before reviewing the broader overlay.

## Apply order

1. Apply the replacement `tools/planning/tm_helper.py`
2. Apply the replacement `tools/mcp/audiagentic-planning/audiagentic-planning_mcp.py`
3. Run a small smoke test for:
   - task creation with explicit workflow
   - work package creation with explicit workflow
   - non-empty doc-sync query result for a known profile pack
4. Then review/apply the rest of the pack

## Smoke test expectation

The following MCP-level calls should succeed after this first fix:

- create task with `workflow`
- create work package with `workflow`
- validate
- reconcile
- index

If those fail, stop there and resolve before applying the rest of the pack.


## Profile-pack YAML shape alignment

The shipped profile-pack files use a top-level `profile_pack:` key.

That means helper lookups must read:

```python
pp = cfg.get("profile_pack", {})
```

not:

```python
pp = cfg.get("planning", {}).get("profile_pack", {})
```

This affects both doc-sync helper paths:

- `get_doc_sync_requirements()`
- `pending_doc_updates()`
