# Research and review evidence

Research records are dated evidence snapshots. They support design and
planning decisions but do not override current source, schemas, configuration,
tests, or the active planning state.

- [Agent capability reviews](agent-capability-reviews/README.md) — durable
  review records for delegated work and competency evidence.

Before reusing a finding, check its date, scope, gateway request/session
identity, validation performed, and whether the referenced implementation
still exists. Reports with `TBD`, `Queued`, or `Running` entries describe the
state observed by that report, not live system state.

Review records must be sanitized before commit: omit resolved user/workspace
paths, machine names, private addresses, temporary locations, credentials, and
copied local runtime payloads. Use repository-relative paths and explicit
placeholders when an environment detail is needed to explain the finding.

See [Documentation status](../DOCUMENTATION_STATUS.md) for the repository-wide
authority and historical-record policy.
