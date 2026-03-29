# DRAFT Performance and Scale Guidance

> Draft guidance only. Not an MVP blocker.

## Purpose

Capture initial expectations for fragment rates, sync cadence, and git-churn mitigation without turning performance into an early blocker.

## Conservative MVP assumptions

- small to medium project
- fragment creation is frequent but bounded
- sync is explicit or on a conservative cadence
- tracked release documents should not be regenerated continuously

## Guidance

- keep `record-change-event` cheap and append-only at runtime
- keep `sync-current-release-ledger` explicit and idempotent
- regenerate `CURRENT_RELEASE.md` only on explicit summary sync
- use release finalization, not frequent tracked-doc churn, as the main consolidation point

## Future measurements to add

- fragments per day
- sync duration by fragment count
- finalize-release duration
- git diff size caused by tracked release docs
