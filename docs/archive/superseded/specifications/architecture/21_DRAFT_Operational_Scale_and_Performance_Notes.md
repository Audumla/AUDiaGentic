# DRAFT — Operational Scale and Performance Notes

## Status
Draft guidance only. Not an MVP blocker.

## Initial operating assumptions
- small to moderate number of change events per day per project
- explicit sync rather than continuous background sync
- git-managed living release files kept small by fragment-first capture

## Early guidance
- prefer many small fragment files during active work and fewer tracked-file rewrites
- run summary/ledger sync at review or check-in boundaries
- rotate event logs according to the event retention policy

## Future concerns
- very large `LEDGER.ndjson` files may later require partitioning or archival
- large multi-agent projects may later need a server-backed event and ledger index
- dashboard/event replay tooling may later require a separate query index
