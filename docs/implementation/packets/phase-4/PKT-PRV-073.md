# PKT-PRV-073 — Qwen sink-harness uplift

**Phase:** Phase 4.9
**Status:** READY_TO_START
**Primary owner group:** Qwen

## Purpose

Move Qwen onto the shared Phase 4.9 sink-based streaming harness so guarded Qwen runs use
AUDiaGentic-owned stream persistence instead of bypassing capture through raw
`subprocess.run(...)`.

## Scope

- replace Qwen raw subprocess execution with `run_streaming_command(...)`
- build Qwen `stdout_sinks` and `stderr_sinks` through `build_provider_stream_sinks(...)`
- preserve the existing guarded bridge/wrapper behavior while adding:
  - `stdout.log`
  - `stderr.log`
  - `events.ndjson`
  - shared console mirroring and stream-control handling
- keep Qwen in the guarded-provider group; this packet owns harness uplift only

## Dependencies

- `PKT-PRV-048`
- `PKT-PRV-038`
- `PKT-PRV-030`

## Not in scope

- Qwen native hook hardening
- Qwen structured completion
- provider-specific event extraction
- shared harness rewrites

## Files likely to change

- `src/audiagentic/execution/providers/adapters/qwen.py`
- Qwen-focused stream harness tests
- Phase 4.9 / Qwen docs only if adapter behavior changes materially

## Acceptance criteria

- Qwen adapter no longer uses raw `subprocess.run(...)` for the primary execution path
- Qwen runs honor shared stream controls from `packet_ctx`
- Qwen runs write `stdout.log`, `stderr.log`, and `events.ndjson` through AUDiaGentic-owned
  runtime artifacts
- shared harness behavior is unchanged for primary providers
- guarded Qwen bridge behavior remains intact

## Notes

- this packet defines explicit ownership for the previously implicit Qwen harness uplift work
- if Qwen later gains provider-specific extraction, track it as a separate follow-on packet
