# Skills and Script Contracts

## Purpose

AUDiaGentic uses deterministic scripts first. Skills are wrappers that call scripts with structured inputs and outputs.

## Script implementation language

For MVP, deterministic scripts are implemented in Python to stay aligned with the core codebase.

## Common CLI envelope

All scripts must support:

```text
<command> --project-root PATH [script-specific flags] [--json]
```

Common exit codes:
- `0` success
- `1` usage or validation error
- `2` blocking business-rule error
- `3` concurrency/lock error
- `4` recoverable warning requiring caller decision
- `5` internal failure

When `--json` is passed, stdout must emit:

```json
{
  "status": "ok",
  "warnings": [],
  "result": {}
}
```

## Required MVP scripts

### `audiagentic-ledger record-change-event`
Inputs:
- explicit structured flags are the canonical MVP interface
- `--event-file PATH` is allowed only as a convenience wrapper and is mutually exclusive with explicit structured flags
Outputs:
- fragment path

### `audiagentic-ledger sync-current-release-ledger`
Outputs:
- count of merged events
- path of rewritten tracked file
- duplicate notices if any

### `audiagentic-ledger sync-current-release-summary`
Outputs:
- summary path

### `audiagentic-release prepare-checkin`
Outputs:
- `docs/releases/CHECKIN.md`

### `audiagentic-release prepare-audit-summary`
Outputs:
- `docs/releases/AUDIT_SUMMARY.md`

### `audiagentic-release finalize-release`
Outputs:
- release result envelope
- checkpoint files

### `audiagentic-jobs run-job-packet`
Inputs:
- `--packet-id`
- `--provider-id`
- `--workflow-profile`
Outputs:
- job record path

## Discovery rule

Skills must refer only to these canonical commands. Providers may wrap them, but must not redefine their contract.


## Flag interaction rules

For `record-change-event`:
- callers must use either explicit structured flags or `--event-file`, never both
- if `--event-file` is provided together with any structured event flag, the script must exit with code `1`
- required explicit fields in MVP are:
  - `--event-id`
  - `--timestamp-utc`
  - `--project-id`
  - `--source-kind`
  - `--provider-id`
  - `--change-class`
  - one or more `--file`

For other scripts:
- defaults must be documented in help text
- all scripts must support `--json`
- all scripts must return the common envelope on stdout when `--json` is requested


## Example invocations

```text
audiagentic-ledger record-change-event --project-root . --event-id chg_20260329_0001 --timestamp-utc 2026-03-29T00:00:00Z --project-id my-project --source-kind interactive-prompt --provider-id claude --change-class code-fix --file src/core/ledger.py --json

audiagentic-ledger record-change-event --project-root . --event-file docs/examples/fixtures/change-event.valid.json --json

audiagentic-ledger sync-current-release-ledger --project-root . --json

audiagentic-release finalize-release --project-root . --json
```

## Canonical explicit flags for `record-change-event`

The canonical explicit MVP flags are:
- `--event-id`
- `--timestamp-utc`
- `--project-id`
- `--source-kind`
- `--provider-id`
- `--change-class`
- repeatable `--file`
- `--technical-summary`
- `--user-summary-candidate`

Optional convenience input:
- `--event-file PATH`

Mutual exclusivity:
- `--event-file` must not be combined with any explicit event field
- script help text must state this rule explicitly

## JSON envelope examples

Successful result:

```json
{
  "status": "ok",
  "warnings": [],
  "result": {"fragment-path": ".audiagentic/runtime/ledger/fragments/2026-03-29T00-00-00Z__chg_20260329_0001.json"}
}
```

Blocking business-rule error:

```json
{
  "status": "error",
  "warnings": [],
  "result": {"error-code": "duplicate-event-id", "message": "event-id already exists with different payload"}
}
```
