# runtime/state/

Durable runtime-only persistence layer for job records and session state.

## Purpose

Owns the persistence side of job execution:
- Job record storage and retrieval
- Review report and bundle persistence
- Session input capture

## Owns

- **jobs_store.py**: Job record read/write (moved from execution/jobs/store.py)
- **reviews_store.py**: Review persistence (extracted from execution/jobs/reviews.py)
- **session_input_store.py**: Session input capture (moved from execution/jobs/session_input.py)

## Must not own

- Job orchestration state machine
- Review build/validation logic (stays in execution/jobs/reviews.py)
- Prompt parsing or execution

## Boundary with execution/jobs/

- `execution/jobs/` owns orchestration semantics (build, validate, transition)
- `runtime/state/` owns durable storage (write, read, append)
- Both share the data structures; state calls back to jobs for validation during reads

## Migration notes

- `jobs_store.py` moved from `execution/jobs/store.py` (Slice E, 2026-04-12)
- `reviews_store.py` extracted from `execution/jobs/reviews.py` (Slice E, 2026-04-12)
- `session_input_store.py` moved from `execution/jobs/session_input.py` (Slice E, 2026-04-12)
