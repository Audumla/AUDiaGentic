# DRAFT — Optional Server and Session Mirroring

## Status
Draft future note. Not part of MVP.

## Current MVP position
- jobs, release, and lifecycle operate without requiring a server process
- Discord in MVP is an overlay over release summaries, job state, and approvals
- full conversational mirroring is deferred

## Future seam
If an optional server is later added, it should sit behind the existing core service contracts and event publisher rather than forcing contract rewrites.

## Deferred topics
- provider session mirroring in native IDE surfaces
- long-running event replay APIs
- multi-surface live conversation ownership
