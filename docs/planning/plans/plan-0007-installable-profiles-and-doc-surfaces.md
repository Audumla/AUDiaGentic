---
id: plan-0007
label: Implement installable profiles and documentation surfaces
state: draft
summary: Deliver an implementation-ready plan for installable profile packs, documentation surfaces, references docs, manifest scaffolding, and MCP expansion.
spec_refs:
  - spec-0021
work_package_refs:
  - ref: wp-0005
    seq: 1000
    display: '1'
  - ref: wp-0006
    seq: 2000
    display: '2'
  - ref: wp-0007
    seq: 3000
    display: '3'
---

# Objectives

Ship a branch-aligned delta that extends the planning component without changing the core planning hierarchy or violating the template installation contract.

# Delivery Approach

Work in three packages:
1. Config, profile-pack, docs, and manifest scaffolding
2. MCP/API expansion and section navigation notes
3. Supporting docs, subsection access, and doc-sync obligations

# Dependencies

- existing planning-module-implementation branch structure
- existing schemas/config split
- existing MCP server entrypoint
- architecture docs 12 and 50
- current planning validator/indexer behavior

# Tracks

- config and schema
- docs and references
- MCP and API
- install/migration scaffolding
- supporting docs and doc sync
- validation and tests
