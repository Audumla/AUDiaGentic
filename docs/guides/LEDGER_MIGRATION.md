# Moving a project to the per-event ledger

For projects that already record change events with `record_change_event` and track
`docs/releases/CURRENT_RELEASE_LEDGER.ndjson`.

## What changed

| Before | Now |
|---|---|
| Every recorded event was appended to the tracked `CURRENT_RELEASE_LEDGER.ndjson`, so each PR touched the same last lines and every other open PR conflicted. | Every event is its own tracked, write-once file `docs/releases/events/<sha256-of-event-id>.json`. Two PRs never share a path. |
| A runtime fragment, then a sync step, wrote the shared file. | There is no fragment or sync step. `sync_ledger` only validates and reports the pending count. |
| A recording could edit the plan item's `Ledger-events` section and Change Log. | Recording never edits a plan file. A plan item's events are derived from `plan-item-ids`: `get_plan_item_events(item_id)`. |
| Release finalize archived events into `LEDGER.ndjson` and reset `CURRENT_RELEASE_LEDGER.ndjson`. | Finalize writes only `LEDGER.ndjson` (and the release documents). Pending means "not in `LEDGER.ndjson`". Event files and the old file are never edited or deleted. |
| `CURRENT_RELEASE.md`, `AUDIT_SUMMARY.md` and `CHECKIN.md` were rewritten in every PR. | They are untracked projections under `.audiagentic/runtime/ledger/generated/`. `CURRENT_RELEASE.md` is written (tracked) only by release finalize. |

`CURRENT_RELEASE_LEDGER.ndjson` stays in the repository as a **frozen, read-only baseline**: it is read, never written,
and its rows are not split into files. Nothing needs to be rewritten to adopt this.

## Cutover

1. Take the AUDiaGentic release that contains the per-event ledger. Agents must pick it up (restart their `ag-ledger`
   MCP server) before they record again; an older tool still appends to the frozen file.
2. Update your release tooling to read events through `audiagentic.components.ledger.current_events`:
   `iter_events(project_root, ref=None)` for every recorded event (baseline first, then event files by
   `(timestamp-utc, event-id)`), `pending_events(...)` to exclude released ids, both accepting a git ref or sha so a tagged
   release is reproducible. Release tooling that read the baseline path directly must switch to this loader.
3. Commit the `docs/releases/events/*.json` file that `record_change_event` wrote with the work it describes.
4. Update release workflows: finalize no longer touches `CURRENT_RELEASE_LEDGER.ndjson` (the generated templates were
   updated; regenerate or edit `git add` and any changed-file allowlist accordingly).

## Branches cut before the cutover

A branch that appended rows to the baseline conflicts when it meets a main that froze it. Convert it **before** merging or
rebasing, while its appended rows are intact: fetch the target base, then run the `convert_legacy_ledger` tool of the
`ag-ledger-mgmt` MCP server (pass the `worktree` of the branch; or `ledger_api.convert_legacy_baseline`) with the base ref
(default `origin/main`). The rows the branch added are those that are not in the baseline at the branch's merge base with that ref; their position does not
matter, so a branch that already merged main once with a union resolution (its rows interleaved before main's) converts normally. The
tool moves each into its own event file, verifies them, and restores the baseline to the merge base's content (or removes it if
the base never had one), so the branch no longer changes that file. Commit the event files and the restored baseline, then
rebase or merge; there is no ledger conflict left.

It refuses, changing nothing, when the baseline lost, changed or reordered a row the merge base holds (an edit, a deletion, a
reorder, or a merge that left conflict markers), or when any appended row is invalid or conflicts with a known event id. Rejected rows are listed
with their line numbers; fix or re-record them and run the tool again. Nothing is written until every row is proven convertible. A byte-identical copy of a row the base already holds is dropped by
the restore and listed as `already-present`. **Stop recording on the branch while you convert**: the tool takes the ledger lock,
but an older ledger tool appending to the baseline at the same moment would not be excluded. If it fails while writing, only
complete, verified event files remain and the baseline is untouched; run it again to finish.

**A branch that is already conflicted:** abort the merge or rebase, then convert as above. If you must resolve in place, take the
branch's own version of `CURRENT_RELEASE_LEDGER.ndjson` (`git checkout --ours` during a merge into the branch,
`git checkout --theirs` during a rebase) so the file is parseable and still holds your appended rows, then run the tool.

## Legacy rows

The loader tolerates what old tooling wrote into the baseline and reports it (also in the generated audit summary) instead
of hiding it: a row with no `event-id` gets a deterministic synthetic `legacy-line-<line>-<digest>` id on read; an unknown
`change-class` or a missing `timestamp-utc` or summary loads as it is. A row the strict contract rejects cannot be archived:
the first release after cutover fails closed on it until it is repaired. Decide those rows (for example move them to event
files with the right class) before the first release.

## Events an older layout left behind

An older machine can still hold events in `.audiagentic/runtime/ledger/fragments/` or `event-outbox/`. `sync_ledger` and the
release archive materialize them into event files first (verified before deleting). A record that cannot be migrated is left in
place, listed by `sync_ledger` as `legacy-left-in-place`, and the **release is refused** until it is repaired or removed, so no
event silently misses a release. This is a bounded exception to "no compatibility paths": plan item LE04 removes
`legacy_runtime.py` once the release after the cutover has shipped.

## Result keys that changed

The generated release workflows assume the default `docs/releases` layout (paths are fixed in the templates); a project that
relocates `releases-dir` or `historical-ledger` must adjust its workflow to match.

`record_change_event`: `fragment-path` is now `event-path`, and `pending-count` is added. `sync_ledger`: `pending-count`,
`migrated-legacy-events`, `legacy-left-in-place`, `warning`. `get_ledger_status`: `event-file-count`, `pending-count`, `events-dir`, `generated-dir`.
Release archive: no `purged-fragments` or `recovered-current`.
