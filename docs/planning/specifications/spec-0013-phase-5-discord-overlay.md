---
id: spec-0013
label: Phase 5 Discord Overlay
state: draft
summary: Add Discord as overlay using approval + events
request_refs:
- request-0002
task_refs: []
---

# Phase 5 — Discord Overlay

## Purpose

Add Discord as a true overlay using approval + events only.

## Scope

- Event subscriber
- Release summary publishing
- Approval publishing/response handling
- Lifecycle/migration notices

## Out of scope

- core functionality
- provider execution

## Implementation order

1. [PKT-DSC-001](task-0158) — event subscriber
2. [PKT-DSC-002](task-0159) — release summary publishing
3. [PKT-DSC-003](task-0160) — approval publishing/response handling
4. [PKT-DSC-004](task-0161) — lifecycle/migration notices

## Exit gate

- Discord overlay functional
- Events processed correctly
- Approvals handled
- Notices sent

# Requirements

1. Discord must be an overlay only
2. Events must be processed correctly
3. Approvals must be handled

# Constraints

- No core functionality changes
- No provider execution

# Acceptance Criteria

1. Discord overlay functional
2. Events processed correctly
3. Approvals handled
4. Notices sent
