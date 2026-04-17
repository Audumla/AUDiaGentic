---
id: request-12
label: Require request linkage for every planning specification, with cascade archive
state: closed
summary: Enforce that specifications cannot be created or retained without at least
  one valid request reference; prevent removal of the last request reference from
  an existing spec; and implement cascade archive so that archiving a request or spec
  propagates to all downstream docs solely owned by that item.
source: codex
current_understanding: Specifications are design responses to tracked intake, so orphan
  specs weaken traceability, standards inheritance, and planning closure. The planning
  API, helper surface, MCP tools, and schema should require at least one request reference
  for spec creation. Removing the last request reference from an existing spec should
  be a hard block. Archiving or superseding a request should cascade to all specs
  (and their downstream plans, tasks, work packages) that have no other active request
  references; archiving or superseding a spec should cascade to all plans/tasks/WPs
  that have no other active spec references.
open_questions:
- Should cascade archive be automatic or manual?
- How should we handle specs with multiple request refs?
standard_refs:
- standard-1
- standard-6
- standard-9
spec_refs:
- spec-11
---



# request-12

## Understanding

Specifications should always trace back to explicit intake. A spec without a request reference is a planning-layer integrity bug, not a valid steady state. The creation paths should reject orphan specs, and the existing workflow-state spec should be attached to a real request.

Cascade archive closes the lifecycle loop: if a request is archived, all downstream docs it solely owns should be archived too, rather than becoming orphans. This makes Q2's hard block safe — if you want to remove the last request reference, you archive the request instead, and cascade handles the cleanup.

## Decisions

## Q1: Orphaned specs during validation

**Decision**: Hard error (not warning) for specs with no active request references during full-repo validation.

**Rationale**: An orphan spec is a planning integrity bug. Warning-level drift allows the state to persist indefinitely. Hard errors force resolution.

## Q2: Removing last request reference from existing spec

**Decision**: Hard block — the API, helper, and MCP must reject a `relink`/unlink operation that would leave a spec with zero request references.

**Rationale**: Cascade archive is the correct path for retiring a spec. If the request is being archived, cascade handles the downstream cleanup automatically. Allowing unlink-to-zero creates orphans that Q1 would then error on.

## Cascade Archive

**Decision**: Archive and supersede operations cascade to all docs solely owned by the affected item.

**Behavior**:

- Archiving or superseding a **request** → applies the same terminal state to all specs whose only active request ref is this request; each cascaded spec then triggers the spec-level cascade
- Archiving or superseding a **spec** → applies the same terminal state to all plans, tasks, and work packages whose only active spec ref is this spec
- "Solely owned" = the item has no other active (non-archived, non-deleted, non-superseded) references pointing to it
- The cascaded state mirrors the parent: archive propagates archive, supersede propagates supersede

**Scope (v1)**:

- Cascade applies to: request→spec, spec→plan, spec→task, spec→work_package
- No cascade for standards or other non-lifecycle items
- Cascade is atomic: all-or-nothing within the affected subgraph

## Open Questions

- Should cascade archive be automatic or manual?
- How should we handle specs with multiple request refs?

## Notes

This request repairs the current `spec-011` orphan condition by attaching it to this intake and tightening the planning-layer guardrails so the same issue cannot recur through API, helper, or MCP creation paths.

Cascade archive was added to this scope because the hard block on Q2 (removing last request ref) requires a clean lifecycle exit path. Without cascade, archiving a request leaves downstream specs as orphans. With cascade, the full subgraph is retired cleanly.

The current archive implementation in `spec-001` explicitly excluded cascade — this request extends that spec's scope.
