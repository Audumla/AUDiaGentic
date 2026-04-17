# File Ownership Matrix

## Tracked docs ownership

| Path | Owner | Write timing |
|---|---|---|
| `docs/releases/CURRENT_RELEASE_LEDGER.ndjson` | `sync-current-release-ledger` | explicit sync / finalize |
| `docs/releases/CURRENT_RELEASE.md` | `sync-current-release-summary` | explicit sync / finalize |
| `docs/releases/CHECKIN.md` | `prepare-checkin` | explicit command / finalize |
| `docs/releases/AUDIT_SUMMARY.md` | `prepare-audit-summary` | explicit command / finalize |
| `docs/releases/CHANGELOG.md` | `finalize-release` | release finalization only |
| `docs/releases/RELEASE_NOTES.md` | `finalize-release` | release finalization only |
| `docs/releases/VERSION_HISTORY.md` | `finalize-release` | release finalization only |
| `.github/workflows/release-please.yml` | lifecycle + release strategy baseline manager | enablement / update / cutover |

## Runtime ownership

| Path prefix | Owner |
|---|---|
| `.audiagentic/runtime/ledger/fragments/` | `record-change-event` |
| `.audiagentic/runtime/ledger/sync/` | ledger sync/finalize scripts |
| `.audiagentic/runtime/jobs/` | job service |
| `.audiagentic/runtime/approvals/` | approval core |
| `.audiagentic/runtime/logs/` | lifecycle, jobs, approval, release services |
