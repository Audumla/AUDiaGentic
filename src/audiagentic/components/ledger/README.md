# components/ledger/

Release management, audit, and change tracking for the system.

## Purpose

Governs the release lifecycle:
- Per-event ledger storage and release archiving
- Change event recording
- Audit and checkin report generation
- Release finalization
- Version bootstrapping

## Owns

- Tracked per-event records (`docs/releases/events/`), the frozen legacy baseline and the historical ledger (NDJSON)
- Audit and release summary generation
- Release bootstrap and lifecycle
- History import from legacy formats
- `contracts/`: Change event, lifecycle plan, and lifecycle result JSON Schema definitions

## Key modules

- **current_events.py**: the one reader/writer of current events (write-once event files, frozen baseline, git-ref reads)
- **recorder.py**: Change event recording
- **sync.py**: Ledger write lock and current-ledger validation
- **audit.py**: Audit and checkin report generation
- **current_summary.py**: Release summary generation
- **ledger_bootstrap.py**: Release workflow initialization
- **ledger_mcp.py**: MCP tool interface for ledger operations
- **ledger_manage_mcp.py**: MCP management tools for ledger
- **ledger_api.py**: Ledger API surface
- **archive.py**: Ledger history archiving

## Storage

Each recorded event is its own tracked, write-once file `docs/releases/events/<sha256(event-id)>.json`, so two
branches that record different events never touch the same path and git needs no merge driver (GitHub's mergeability
ignores custom merge drivers). The old shared `CURRENT_RELEASE_LEDGER.ndjson` is a **frozen legacy baseline**: read by
the loader, written by nothing. `iter_events(project_root, ref=None)` returns the baseline (tolerant of legacy
anomalies; a row without an `event-id` gets a deterministic synthetic `legacy-line-<n>-<digest>` id on read) followed
by the event files ordered by `(timestamp-utc, event-id)`, from the working tree or from any git ref, so a tagged
release is reproducible. Summaries and audit/check-in documents are untracked projections under
`.audiagentic/runtime/ledger/generated/`; no normal operation writes a tracked file other than the event file itself.

## Public API for downstream consumers

Downstream release tooling (for example release-notes generators) reads events through the ledger's read functions and
nothing else; reimplementing the file layout is unsupported. They are defined in
`audiagentic.components.ledger.current_events` and re-exported from `audiagentic.components.ledger.ledger_api` (an in-repo
component imports `ledger_api`; an external consumer may import either module). From 0.97 these are the stable names: `iter_events(project_root, *, ref=None)`, `pending_events(project_root, *, ref=None)`,
`released_events(project_root, *, ref=None)`, `anomalies(project_root, *, ref=None)` and `event_file_name(event_id)`. A change to
a signature, to the returned dict contents, or to the order guarantee is a breaking change and is called out in the release
notes. `project_root` is the repository root; no `.audiagentic/` directory is needed (the default layout applies, and a
`paths:` block in `.audiagentic/components/agent-ledger.yaml` overrides it if present). Reads with `ref` need `git` on the
`PATH` and take a ref name or a full sha; they resolve the ledger paths from the working tree's configuration, not from the
ref, so they are reproducible only while those paths have not changed since the ref (a path missing at the ref reads as
empty). The default layout has never changed. The module imports the audiagentic package, so a consumer installs `audiagentic`
(`pip install "audiagentic>=0.97"`); there is no slimmer distribution of the loader.

## Release boundary

`archive_for_release(project_root, release_id)` is the only release archival boundary. Pending means "not in the
historical ledger", so a release writes only `LEDGER.ndjson` (and resets the release summary): it never edits or
deletes an event file or the baseline, and a stale branch carrying an already released event cannot make it pending
again. A retry for an already archived release returns its immutable event IDs and cannot claim events that arrived
for the next release. A legacy row the strict contract rejects, a conflicting historical identity or a malformed
persisted record fails closed with a typed ledger error before anything is written.

Source-control commit stamping is deliberately disabled by default. Release
finalization must never stamp its own generated commit back into the ledger;
otherwise archive output changes after the commit and creates a feedback loop.

## Must not own

- Job orchestration
- Provider execution
- Runtime lifecycle (install, update, uninstall)

## Migration notes

- Moved from `runtime/release/` to top-level `release/` (Slice F, 2026-04-12)
- Now a first-class domain, not a runtime subdomain
