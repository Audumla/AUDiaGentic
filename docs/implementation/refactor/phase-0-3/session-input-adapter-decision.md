# Session Input Adapter Decision

## Scope

- checkpoint date: 2026-04-02
- owner: Phase 0.3 checkpoint
- packet: PKT-FND-011
- status: frozen first-pass decision

## Decision

For the Phase 0.3 refactor:

- `execution/jobs/session_input.py` remains responsible for canonical session-input record creation
- session-input output must become adapter-driven rather than hard-coded directly to disk
- adapters live under `src/audiagentic/streaming/adapters/*`
- the adapter shape must stay simple, but it must support **multiple sinks** rather than a single hard-wired output target
- the required first adapter is `disk`, which preserves current runtime-file behavior
- a broader streaming unifier may be added later and is not required for this checkpoint

## First-pass implications

- Phase 0.3 does **not** require a generalized stream router or event bus
- Phase 0.3 does **not** require Discord or other non-disk adapters to be implemented yet
- Phase 0.3 does require the seam to be designed so additional sinks can be added later without changing the canonical session-input record shape

## Minimal implementation expectation

A minimal acceptable first-pass structure is:

```text
src/audiagentic/
  execution/
    jobs/
      session_input.py
  streaming/
    adapters/
      disk.py
```

`session_input.py` should create canonical records and pass them to one or more configured adapters.
The `disk` adapter should preserve the current behavior of writing:

- `input.ndjson`
- `input-events.ndjson`
- `stdin.log`

under the runtime job root.

## Deferred work

The following remain explicitly deferred:

- streaming unifier design
- richer adapter fan-out orchestration
- Discord or other live sink implementations
- refactoring historical persistence helpers into `runtime/state` unless such a split becomes trivial during the move
