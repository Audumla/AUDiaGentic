---
id: task-3253
label: Integrate relationship validation into managers
state: draft
summary: '"Add RelationshipConfig validation to manager create() methods"'
spec_ref: spec-29
request_refs: []
standard_refs:
- standard-5
- standard-6
---

## Description

Integrate `RelationshipConfig` validation into manager create() methods to validate references against config rules.

## Current State

Managers currently have no validation of references - they accept any refs without checking if the relationship is allowed.

## Required Changes

1. Add validation to `SpecMgr.create()` - validate request_refs, standard_refs
2. Add validation to `TaskMgr.create()` - validate spec_ref, request_refs, standard_refs, parent_task_ref
3. Add validation to `PlanMgr.create()` - validate spec_refs, request_refs, standard_refs
4. Add validation to `WPMgr.create()` - validate plan_ref, task_refs, standard_refs
5. Add validation to `StandardMgr.create()` - no refs to validate
6. Add validation to `RequestMgr.create()` - validate spec_refs if present

Validation should:
- Check that refs are in `can_reference` list from config
- Check that required refs are present
- Return/raise errors for invalid relationships

## Acceptance Criteria

- All manager create() methods validate refs using RelationshipConfig
- Invalid references are rejected with clear error messages
- Missing required references are rejected with clear error messages
- Validation happens before document is created
- Existing valid documents can still be created
