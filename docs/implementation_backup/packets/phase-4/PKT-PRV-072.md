# PKT-PRV-072 — Gemini sink-harness uplift

**Phase:** Phase 4.9
**Status:** READY_TO_START
**Primary owner group:** Gemini

## Purpose

Move Gemini onto the shared Phase 4.9 sink-based streaming harness so Gemini runs write
AUDiaGentic-owned runtime stream artifacts instead of bypassing capture through raw
`subprocess.run(...)`.

## Scope

- replace Gemini raw subprocess execution with `run_streaming_command(...)`
- build Gemini `stdout_sinks` and `stderr_sinks` through `build_provider_stream_sinks(...)`
- preserve current Gemini execution semantics while adding:
  - `stdout.log`
  - `stderr.log`
  - `events.ndjson`
  - console mirroring controlled by shared stream controls
- keep Gemini in the guarded-provider rollout group; this packet owns harness uplift, not
  native-hook hardening

## Dependencies

- `PKT-PRV-048`
- `PKT-PRV-034`
- `PKT-PRV-006`

## Not in scope

- Gemini native event extraction
- Gemini structured completion
- Gemini native hook design changes
- shared harness rewrites

## Files likely to change

- `src/audiagentic/execution/providers/adapters/gemini.py`
- Gemini-focused stream harness tests
- Phase 4.9 / Gemini docs only if adapter behavior changes materially

## Acceptance criteria

- Gemini adapter no longer uses raw `subprocess.run(...)` for the primary execution path
- Gemini runs honor shared stream controls from `packet_ctx`
- Gemini runs write `stdout.log`, `stderr.log`, and `events.ndjson` through AUDiaGentic-owned
  runtime artifacts
- console teeing remains Windows-safe and does not crash the run
- shared harness behavior is unchanged for Codex/Cline/Claude/opencode

## Notes

- this packet owns only the Gemini harness uplift seam
- if Gemini later gains provider-specific extraction, that should be tracked as a separate
  follow-on rather than folded into this uplift packet
