# Release Notes

## v0.4.0

### Configuration
- Avoid duplicate full CI runs for feature-branch PR updates while retaining main/release and manual branch validation.

### Features
- Rotate gateway traces daily, compress closed segments and expire eligible raw traces after five days without deleting results or protected recovery evidence.

### Fixes
- Repair CI contract validation and clean-room build/test assumptions without weakening production contracts.
- Prevent CI plugin startup errors and false Pi RPC EOF failures during active long streaming turns.
- Repair CI dependency and stale integration-contract failures while preserving fail-closed gateway routing.
- Prevent bounded journal compaction from repeatedly blocking active streaming sessions and stop duplicate CI runs consuming runner capacity.
- Prevent fast provider progress from being missed when the worker activity watcher starts late.
- Allow release ledger finalization to respect pull-request-only main branch rules.

### Testing
- Bring planning and Pi isolation test fixtures and generated capability reference in line with current contracts.
- Repair Linux CI portability, startup prerequisites, deterministic crash/lease tests, and planning integrity while retaining diagnostic evidence.
- Make real-model smoke prompts and model choice consistent with the working RPC baseline and preserve Windows CLI diagnostics.
- Repair CI test composition for persistent GPT sessions and bound real-model Pi smoke behavior without skipping checks.
- Remove a flaky session-reaper test race while preserving real background cleanup and exact-once assertions.
- Stabilize the real Pi resume smoke test and expose stage timings instead of an opaque fifteen-minute wait.
