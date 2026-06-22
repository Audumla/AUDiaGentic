# components/release/

Release workflow component.

## Intent

Bridge release ledger state to release automation and generated release docs.

## Capabilities

- Report release automation status.
- Install or refresh `release-please` workflow assets.
- Ensure baseline release workflow exists.
- Finalize a release by syncing ledger state, archiving current release events, and rendering release documents.

## Relationship To Ledger

This area does not own change-event capture. `ledger/` owns current and historical release records. `release/` consumes that state to drive automation and final output.
