# PKT-NOD-001 — Node descriptor and identity module

**Phase:** Phase 7  
**Primary owner group:** Nodes

## Goal
Create the node identity contract and runtime helpers.

## Dependencies
- current Phase 4 active provider/runtime work stabilized
- `03_Common_Contracts.md`
- `39_Node_Execution_and_Federation_Extension.md`

## Ownership boundary
- `src/audiagentic/nodes/identity.py`
- `tests/unit/nodes/test_identity.py`
- fixtures for node descriptor validation

## Public outputs
- `NodeDescriptor`
- node id generation rules
- runtime-kind classification rules

## Acceptance
- node identity can be generated without network/discovery dependencies
