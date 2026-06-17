# Decommissioned components

The **planning** and **knowledge** components are decommissioned. Their source,
tests, fixtures, and config are retained here (out of the live `src/` and `tests/`
trees) so the work is preserved and reversible, but nothing loads or runs them.

## Why they are inert

- **Component registration** discovers components by globbing top-level
  `*.yaml` in `src/audiagentic/config/components/{core,optional}/`. With
  `planning.yaml` moved here and no `knowledge.yaml` in the live tree, neither
  component is registered. No external code imports either package.
- **Tests** are collected from `tests/{unit,integration,e2e,deferred}`. With the
  test directories moved here, pytest no longer collects them.

## What is archived (mirrors original paths)

| archived path | original location |
|---|---|
| `src/audiagentic/components/optional/planning/` | same |
| `src/audiagentic/components/optional/knowledge/` | same |
| `src/audiagentic/config/components/optional/planning.yaml` | same |
| `tests/unit/planning/`, `tests/integration/planning/` | same |
| `tests/unit/knowledge/`, `tests/integration/knowledge/` | same |
| `tests/fixtures/planning_config/` | same |
| `tests/helpers/planning_testkit.py` | same |

## Restoring a component

Move the relevant paths back to their original locations (the table above maps
1:1), e.g.:

```sh
git mv archive/decommissioned/src/audiagentic/components/optional/planning \
       src/audiagentic/components/optional/planning
git mv archive/decommissioned/src/audiagentic/config/components/optional/planning.yaml \
       src/audiagentic/config/components/optional/planning.yaml
# ...and the matching tests/ paths
```

Registration and test collection resume automatically once the files are back in
the live trees.

## Related change

The `ag-plan` agent-jobs action was made generic at decommission time — its
scope/approval policy no longer references planning-component artifact types
(requests, specs, plans, tasks). See
`src/audiagentic/config/components/optional/agent-jobs/ag-plan.yaml`.
