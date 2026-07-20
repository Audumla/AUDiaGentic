# 2026-07-19 SH07 Batch Incident — User-Global OpenCode Config Clobbered

Harness incident report for the SH07 delegation batch (C1 / RV741 / RV739
lanes). Not an agent competency review; referenced by the three per-lane
reviews of the same date.

## Symptom

All three first-attempt requests (`req_c225d5d59b464d40`,
`req_190fd714e829434a`, `req_0e8467f2ac694a33`) failed 4-7 seconds after ACP
session open, error redacted to `UNKNOWN unexpected error (see server logs)`.
Sessions showed `close-reason: failed`, turn-count 0, but each had a
`session.turn.started` timeline event — the launch worked, the model turn died.

## Root cause chain

1. `C:\Users\mgs\.config\opencode\opencode.json` (user-global) had been
   replaced by a 98-byte stub `{"provider": {"anthropic": {}, "audiagentic": {}}}`
   with mtime exactly at the first worker launch (07:28Z).
2. The stub content matches config-probe experiments an earlier RV739
   investigation worker ran (visible in the opencode log at 07:21-07:22: python
   snippets constructing exactly that provider map and pointing
   `OPENCODE_CONFIG` at `_source_config_path()` — the real global path).
3. The project `.opencode/opencode.json` has no `provider` block, so gateway
   ACP launches omit `enabled_providers` and opencode falls back to the
   user-global config — which no longer defined `brutus`. Model resolution fell
   through to the cloud `opencode` provider (`big-pickle`/`gpt-5.4-nano`) and
   failed with `AI_APICallError: Invalid API key`.
4. The gateway redacts provider errors to `UNKNOWN`, so none of this was
   visible from request records; diagnosis required the opencode process log.

## Recovery

- The original global config was recovered intact from opencode's own message
  store: a stored `read` tool output in `opencode.db` (part
  `prt_f79253f7a00180dkHdAeP7n07D`) contained the full 150-line file from the
  Jul 17 RV739 investigation. Line-number prefixes stripped, JSON validated.
- Restored to `C:\Users\mgs\.config\opencode\opencode.json` (brutus at
  `http://10.10.100.10:41080/v1` with the coder-quality model family, ymir,
  enabled_providers, hindsight plugin, agent defaults). The stub was preserved
  as `opencode.json.clobbered-20260719`.
- All three lanes resubmitted and completed successfully.

## Durable lessons

1. Worker prompts that involve opencode config experiments must forbid writing
   to or pointing `OPENCODE_CONFIG` at the real global path and require
   tempfile-scoped subprocess env only. This rule is now in the RV739
   verification prompt template and should be standard for any
   provider-config-adjacent handoff.
2. The gateway's `UNKNOWN` redaction plus the RV741 gap made a config-layer
   failure look like a dead worker. The now-landed progress projection helps;
   a follow-up should consider projecting a redacted provider error CLASS
   (auth/config/network) into the public record so operators can triage
   without host log access.
3. The fallback-to-global-config behavior when a project has no `provider`
   block is a standing fragility: worker profiles depend on user-global state
   the harness does not manage or validate. SH07 notes now carry the RV739
   coverage gap; a managed-config item should own materializing the worker
   provider map project-locally.
4. Recovery tip: opencode's `part` table retains full tool outputs — a read of
   a config file in any prior agent session is a de facto backup.
