---
id: plan-8
label: Implement archive functionality
state: done
summary: Implement archive state, state-based archive/restore behavior, and filtering
spec_refs:
- spec-2
standard_refs:
- standard-6
- standard-9
work_package_refs:
- ref: wp-0009
  seq: 1000
---











# Objectives

Implement archive functionality for planning items to enable:
- Archiving older or redundant planning items
- Maintaining historical records
- Querying archived items when needed
- Restoring archived items when needed

# Delivery Approach

1. Add archived state to planning state machine (task-0178)
2. Implement state-based archive and restore behavior in the planning core (task-0179)
3. Update tm_list() with archive filtering (task-0180)
4. Update tm_validate() with archive rules (task-0181)
5. Update tm_show() with archive metadata (task-0182)

# Dependencies

- spec-1: Archive state and functionality specification
- Existing planning state machine
- Existing tm_helper functions
- MCP/helper surface alignment with planning-core behavior

# Risks

1. Breaking existing workflows that rely on current state machine
2. Performance impact of archive filtering
3. Data loss if archive metadata is not properly persisted
4. Behavioral drift between workflow/core semantics and MCP-facing convenience surfaces

# Mitigations

1. Thorough testing of state transitions
2. Performance testing with large item sets
3. Comprehensive archive metadata logging
4. Keep MCP exposure aligned to core state semantics instead of introducing separate archive-only behavior in wrappers
