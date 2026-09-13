# Release documentation

Release documents are maintained through the release component and the
`ag-ledger` workflow. They are not a second source of truth for implementation
behavior.

- [Current release](CURRENT_RELEASE.md) — generated current-release summary.
- [Check-in summary](CHECKIN.md) — generated or synchronized release-facing
  change summary.
- [Release notes](RELEASE_NOTES.md) — published release history.
- [Changelog](CHANGELOG.md) — changelog entries and comparison links.
- [Audit summary](AUDIT_SUMMARY.md) — generated ledger audit view.
- [Current release ledger](CURRENT_RELEASE_LEDGER.ndjson) — current pending
  and released event records.
- [Publishing guide](PYPI_PUBLISHING.md) — PyPI trusted-publishing setup.

Before changing release notes, changelog fragments, or generated summaries:

1. Inspect the current ledger state.
2. Record substantive changes with `record_change_event` and the related plan
   item IDs.
3. Synchronize generated release outputs through the release workflow.
4. Verify that implementation files, plan records, and release records agree.

Do not hand-edit generated output to conceal a missing or incorrect ledger
event. Historical release dates and evidence should remain unchanged.

