# PKT-PRV-064 — opencode provider adapter

**Phase:** Phase 4
**Status:** IN_PROGRESS
**Owner:** opencode

## Objective

Implement the opencode adapter on the shared provider execution seam so AUDiaGentic can launch
canonical jobs through the installed CLI without inventing a provider-specific runtime model.

## What is implemented

- `src/audiagentic/execution/providers/adapters/opencode.py` now invokes the real `opencode`
  CLI through `opencode run`
- adapter execution is routed through the shared sink-based streaming harness
- CLI availability is validated before execution begins
- the adapter normalizes model, command, return code, stdout/stderr, and extracted session/output
  fields into the shared provider result shape
- integration tests exist in `tests/integration/providers/test_opencode.py`

## Remaining review focus

- remove the invalid `--dir` CLI flag; the shared runner `cwd` already owns working-directory handling
- verify the real `opencode` CLI flags still match the adapter assumptions after that fix
- confirm the normalized output extraction remains correct when the CLI returns multiple JSON
  lines or mixed text/JSON output
- add integration coverage for non-zero return codes and empty-output cases

## Acceptance Criteria

- adapter module exists and is wired into the shared provider executor
- missing CLI detection returns a stable AUDiaGentic error
- successful execution returns a normalized provider result envelope
- integration coverage proves command construction and result parsing
