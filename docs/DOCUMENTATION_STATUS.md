# Documentation status and maintenance boundary

Last audited: 2026-09-13

This page records how documentation is maintained while the repository is
being migrated. It prevents historical records from being mistaken for live
contracts and gives agents a reliable route to current guidance.

## Current documentation sources

These areas are maintained as current-facing documentation:

- `docs/standards/`: normative architecture and implementation standards.
- `docs/design/`: approved or explicitly labelled design authority.
- `docs/reference/`: code-facing schemas, registries, and capability evidence.
- `docs/examples/`: configuration and scaffold fixtures that are expected to
  remain valid against current loaders and schemas.
- `docs/README.md`: navigation, authority order, and maintenance rules.

When these documents disagree with source code, tests, schemas, configuration,
or managed repository instructions, the executable/current artifact wins and
the documentation must be corrected in the same work item.

## Historical or generated documentation

- `docs/planning/` is the work ledger. Active items describe intended work;
  completed items and reviews preserve decisions and evidence at the time of
  the work. They are not a replacement for current implementation docs.
- `docs/research/` contains dated investigations and review snapshots. A
  report may contain queued, running, pending, or unverified observations;
  those words describe the snapshot and are not live system status.
- `docs/releases/` contains release-managed notes, ledgers, audit outputs, and
  publishing records. Follow the release ledger process before modifying
  these files; do not hand-edit generated output to repair a documentation
  discrepancy.

Historical records should be corrected only when they contain a misleading
current-facing statement, a broken link that prevents navigating history, or
an integrity problem. Preserve the original dates, conclusions, and evidence.

## Audit findings recorded so far

- A repository-wide Markdown-link scan on 2026-09-13 covered 1,773 Markdown
  files and 112 local links. It found no genuine missing local target; the one
  apparent hit was `managed_id` inside inline code in a historical planning
  record, not a Markdown link.
- A case-insensitive filename audit found no duplicate paths under `docs/`, so
  documentation filenames are unambiguous on Windows filesystems.
- The provider capability reference manifest declares 42 package files; all 42
  exist. Remaining maintenance for that package is evidence freshness and
  capability revalidation, not repairing missing manifest artifacts.
- The remaining pre-2026 dates in current-facing reference files are confined
  to historical/probe evidence and are labelled as such; current validation
  dates remain part of each report's evidence metadata.
- The documented example/scaffold contracts are exercised by
  `tests/integration/test_example_scaffold.py` and
  `tests/unit/contracts/test_schema_validation.py`; together they passed 7
  tests on 2026-09-13.
- The repository README previously linked to non-existent `docs/layout.md`,
  `docs/testing/`, `docs/knowledge/`, and `docs/archive/` trees; those links
  have been removed or replaced with existing documentation entry points.
- The component path in the repository README previously named the removed
  `src/audiagentic/components/optional/` layout; it now points to the current
  `src/audiagentic/components/` tree.
- The gateway execution-context design is the completed SH02 v1 contract
  baseline, not an unqualified draft. Its future-field notes remain because
  later schema additions require their owning work items.
- The shared-gateway design records a frozen target boundary. Its status note
  now distinguishes the completed SH04–SH11 migration from active follow-on
  work.
- The provider capability reference contains deliberately dated evidence;
  each fact's validation timestamp must be respected rather than inferred from
  the package's rebuild date.
- Testing guidance is maintained at `tests/TESTING.md`, outside `docs/`; the
  canonical docs map links to it instead of recreating a second test guide.

## Maintenance checklist

Before changing current-facing documentation:

1. Identify the owning source, schema, configuration, test, or plan item.
2. Search all current-facing docs for the old name, path, field, and contract.
3. Update the canonical explanation and replace duplicates with links where
   practical.
4. Label retained historical material instead of rewriting its chronology.
5. Run `git diff --check` and a local-link scan for Markdown targets.
6. Record substantive documentation changes in the release ledger with the
   related plan-item ID.
