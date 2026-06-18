<!-- MANAGED_BY_AUDIAGENTIC: do not edit directly. -->

<!-- ag:managed:begin -->
_Managed by AUDiaGentic — generated from component configs. Edit the owning component and re-run surface apply; edits here are overwritten._

## Agent ledger process

After substantive implementation work, record a change event with the ag-ledger
MCP tool record_change_event — the ledger is the authoritative release record.
Required fields: change-class, files, technical-summary, user-summary-candidate,
status ('unreleased'). Other fields are auto-generated.
- Check release ledger state before changing release notes, changelog fragments, or release workflow files.
- Keep release artifacts and job records synchronized with implementation and review outcomes.
- Do not bypass ledger updates by editing generated release outputs only.

## Release doctrine

Use the configured release manager for versioning and publication.
Do not edit generated release artifacts (CHANGELOG.md, RELEASE_NOTES.md) directly.
Run finalize_release only after ledger audit review is complete.
The ledger is archived as part of finalization — this cannot be undone.

## Source control doctrine

Do not invoke git or GitHub APIs directly — use the MCP tools.
<!-- ag:managed:end -->
