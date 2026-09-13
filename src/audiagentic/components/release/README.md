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

Release finalization consumes the event IDs returned by the ledger archive
operation, then renders grouped, user-facing release notes from that exact
snapshot. The standard GitHub workflow updates the GitHub release body from
`docs/releases/RELEASE_NOTES.md` after finalization. Re-running finalization
refreshes derived notes without duplicating changelog or version-history
sections.
