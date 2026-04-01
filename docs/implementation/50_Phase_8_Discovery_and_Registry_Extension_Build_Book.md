# 50 — Phase 8 Discovery and Registry Extension Build Book

## Goal

Add pluggable node discovery/registration without making it a baseline dependency.

## Deliverables

- locator provider contract
- static registry provider
- operator-configurable registry selection
- optional zeroconf provider
- optional external catalog provider seam

## Sequence

### Phase 8
- implement static registry provider first

### Phase 8.1
- optional zeroconf provider

### Phase 8.2
- optional external registry provider

### Phase 8.3
- future alternative registry backends

## Exit gate

Phase 8 is complete when:
- nodes can be listed and resolved via static registry
- node register/deregister/heartbeat operations are deterministic
- failure degrades to local-only mode
