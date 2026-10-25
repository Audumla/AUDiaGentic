# Merge and release validation

Pull requests and main pushes run contracts, privacy and the fast critical gateway
plus changed-component tests. These remain independent of full qualification.

Generated release PRs have a strict file allowlist and exact-head privacy checks.
They run schema/ID validation and release automation regression tests rather than
repeating application gateway tests for version-only changes. Ledger finalization
retains its privacy gate. Publication builds from the exact finalized commit,
installs the actual wheel in isolation, checks version/CLI/gateway imports and
records distribution hashes before publishing those same bytes.

After successful PyPI publication, Release explicitly dispatches `ci-full.yml`
with the immutable finalized source SHA. This dispatch is necessary because
GITHUB_TOKEN-created releases do not reliably start other event workflows.
Publication does not wait for the full suite. Dispatch failure is a visible failed
Release job; publication may already have succeeded. Retry only that failed job
to schedule validation, rather than republishing the artifacts.

Full validation also runs nightly, manually (`source_ref` accepts an exact SHA),
or on PR updates carrying the `ci-full` label. Main pushes and release events do
not independently start duplicate full runs. Background failures remain failures
and create/update the existing CI failure issue, with source identity and run URL.
A successful publication is not proof of full-suite success; inspect the full
run's coverage audit and recipe jobs separately.
