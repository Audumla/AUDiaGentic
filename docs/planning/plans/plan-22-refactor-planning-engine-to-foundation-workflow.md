---
id: plan-22
label: Refactor planning engine to foundation/workflow
state: draft
summary: Move PlanningAPI to foundation/workflow as generic WorkflowAPI with configurable
  workflow instances.
request_refs:
- request-36
spec_refs:
- spec-55
standard_refs:
- standard-0006
---




# Objectives


# Delivery Approach


# Dependencies

# Objectives

1. Move planning engine to foundation/workflow as generic WorkflowAPI
2. Make counter management config-driven instead of hardcoded
3. Build working automation engine that connects automations.yaml to EventBus
4. Ensure planning continues to work as a configured instance

# Delivery Approach

Work in four packages:

1. **Foundation skeleton** - create directory structure, move generic modules
2. **Configurable config** - add workflow_name parameter, move counter management to config
3. **Automation engine** - build automation runner, connect to EventBus
4. **Backward compat** - PlanningAPI wrapper, update import paths

# Dependencies

- spec-55: Generic workflow engine specification
- request-2: Move planning engine to foundation/workflow
- Existing EventBus in audiagentic.interoperability (already generic)

# Risks

1. Breaking existing imports across the codebase
2. Tests that depend on planning-specific paths
3. Counter migration from per-kind files to consolidated file
4. v2 MCP server needs import path updates

# Mitigations

1. Keep PlanningAPI as thin wrapper for backward compat
2. Run full test suite after each migration step
3. Migrate counters as part of the refactor, not separately
4. Update v2 MCP server as final step

# Sequencing

1. Create foundation/workflow/ directory structure
2. Move generic modules (events, claims, indexer, validator, etc.)
3. Add workflow_name parameter to Config, API, submodules
4. Consolidate counter management into config-driven counters.json
5. Build automation engine
6. Create PlanningAPI wrapper
7. Update import paths (v2 MCP server, CLI, tests)
8. Run full test suite
