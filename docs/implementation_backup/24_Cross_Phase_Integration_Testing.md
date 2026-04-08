# Cross-Phase Integration Testing

## Purpose

Ensure later phases layer on top of earlier cores without rewriting them.

## Required tests by phase

### Phase 2
- release flow works with no jobs and no providers

### Phase 3
- job runner uses Phase 2 release scripts and cannot write tracked release docs directly

### Phase 4
- real provider selection and health checks attach to the Phase 3 job seam without changing Phase 3 contracts

### Phase 5
- Discord can be disabled and all earlier phases still function

### Phase 6
- migration and cutover validate earlier lifecycle behavior rather than replacing it

## Regression rule

If a later phase discovers a bug in an earlier phase:
1. raise a change-control note
2. patch the earlier owner module only
3. add a regression test
4. do not silently broaden the later packet
