# Ambiguity Report

## Scope

- checkpoint date: 2026-04-02
- owner: Phase 0.3 checkpoint
- packet: PKT-FND-010
- status: seeded from repository realignment view and frozen decisions to date

## Ambiguity Records

### Record 1

- current path: `src/audiagentic/providers/streaming.py`
- dominant responsibility: shared streaming command execution helper
- secondary responsibility: provider adapter support
- target domain recommendation: likely `src/audiagentic/streaming/*` later; may remain temporarily colocated with provider execution during initial move
- split or keep together in first pass: keep together in first pass unless clean adapter extraction is trivial
- compatibility shim likely required: no
- reason: execution moves should not stall on helper extraction; adapter seam can be frozen first and helper relocation can follow

### Record 2

- current path: `src/audiagentic/jobs/store.py`
- dominant responsibility: durable job record persistence and runtime-path layout
- secondary responsibility: execution support
- target domain recommendation: later candidate for `src/audiagentic/runtime/state/*`
- split or keep together in first pass: keep together in first pass
- compatibility shim likely required: no
- reason: structurally important but not necessary to split during checkpoint unless separation becomes trivial

### Record 3

- current path: persistence helpers inside `src/audiagentic/jobs/reviews.py`
- dominant responsibility: review artifact persistence and runtime-path layout
- secondary responsibility: review domain logic
- target domain recommendation: later candidate for `src/audiagentic/runtime/state/*`
- split or keep together in first pass: keep together in first pass
- compatibility shim likely required: no
- reason: mixed file, but persistence extraction can be deferred safely

### Record 4

- current path: `src/audiagentic/jobs/session_input.py`
- dominant responsibility: execution-side session input record creation
- secondary responsibility: hard-coded disk persistence
- target domain recommendation: `execution/jobs/session_input.py` plus output adapters under `streaming/`
- split or keep together in first pass: split by seam, not by over-refactoring; keep record creation in execution and move sinks/adapters under streaming
- compatibility shim likely required: no
- reason: decision frozen that session input should become adapter-driven with default disk behavior preserved

### Record 5

- current path: `src/audiagentic/scoping/*` (not yet present)
- dominant responsibility: future request/scope/plan shaping code domain
- secondary responsibility: none yet
- target domain recommendation: reserve `src/audiagentic/scoping/*`
- split or keep together in first pass: keep deferred
- compatibility shim likely required: no
- reason: scoping is deferred for this tranche and should not drive code motion now

## Shared Themes

- repeated boundary problems:
  - execution logic mixed with durable runtime persistence
  - provider execution helpers mixed with future streaming concerns
- likely shim-heavy areas:
  - legacy public import roots under `jobs`, `providers`, `lifecycle`, `release`, `server`, `overlay/discord`
- areas that should not be over-split in the first pass:
  - provider adapters
  - prompt launch / prompt parser / prompt bridge
  - review helper modules unless the split is trivial

## Terminology Ambiguity Findings

For Phase 0.3 inventory, also capture any blurred canonical terms that may affect later cleanup.

### Term Record 1

- current term: Job / Run
- location/path: execution and runtime docs/code paths
- competing or overlapping term: execution run, provider execution, runtime job artifacts
- why the meaning is blurred: orchestration semantics and durable runtime state both use job-shaped language
- affects structure now or later: later
- recommended follow-up: terminology cleanup pass after structural checkpoint

### Term Record 2

- current term: Request / Prompt Launch Request / Session Input
- location/path: `jobs/prompt_parser.py`, `jobs/prompt_launch.py`, `jobs/session_input.py`
- competing or overlapping term: request, input, prompt body, launch payload
- why the meaning is blurred: related but distinct envelopes are all execution-facing records
- affects structure now or later: later
- recommended follow-up: capture only, no bulk rename in Phase 0.3

## Decisions Required from PKT-FND-011

- target-tree questions:
  - none beyond preserving reserved extension roots and deferred scoping root
- ownership questions:
  - none for prompt bridge; session input seam already frozen
- dependency-rule questions:
  - ensure streaming adapters are treated as streaming-side sinks, not execution-side orchestration owners
- terminology questions that must not remain ambiguous through code motion:
  - none; terminology cleanup deferred
