---
id: EDJ03
order: 60
plan: event-driven-jobs
state: completed
validate-first: true
priority: P1
work: L
---

# Create durable job records from event triggers

## Description

When a configured trigger fires, create a durable agent job record that captures trigger provenance, event metadata, target, workflow profile, prompt source, rendered instructions, and prompt context summary. Link the job to downstream gateway requests so operators can trace job -> agent execution.

## Steps

1. Extend both component and foundation copies of `job-record.schema.json` for event provenance; keep contract-version v1 additive and registry-compatible:
   - add `"event"` to `launch-source.surface` enum (currently cli|vscode)
   - add optional top-level `event-source` object: {`event-type` (string), `trigger-id` (string), `correlation-id` (string|null), `subject` ({kind,id}|null), `source-component` (string), `received-at` or `occurred-at` (iso string, mapped explicitly from `EventEnvelope.occurred_at` unless separate receive time is needed)}, additionalProperties:false
   - gateway linkage: append to existing `artifacts` array an entry {`kind`:"gateway-request", `request-id`:string} rather than moving any gateway record into agent-jobs
   - prompt provenance: store inline/file source metadata and redacted context key summary, not full raw large payloads
2. Keep schema registry/canonical IDs synchronized for new job-record fields.
3. Extend `prompt-launch-request.schema.json` only as part of the consolidated EDJ10/EDJ11 schema update so `agent-profile-id`, `prompt-template-file`, and explicit `context` validate consistently with parser behavior.
4. Extend `records.py` `build_job_record()`/`JobRecord` rather than bypassing it, adding typed inputs such as `event_source` and `launch_source.surface='event'`.
5. Add a trigger-origin job builder path that populates job-id, project-id, workflow-profile (from trigger/default), state `created`, and the `event-source` block.
6. Persist launch-source.surface=`event` plus inbound event_type/trigger-id/metadata.correlation_id/metadata.subject.
7. Record the first job timeline entries via `foundation.observability.record_timeline_event` and EDJ07's canonical `job_timeline_path` helper/format.
8. Do not persist gateway request id in the creation path; EDJ05 outcome handler appends the `gateway-request` artifact after lifecycle correlation.

## Files

src/audiagentic/components/agent_jobs/records.py
src/audiagentic/components/agent_jobs/jobs_store.py
src/audiagentic/components/agent_jobs/prompt_launch.py
src/audiagentic/components/agent_jobs/paths.py
src/audiagentic/components/agent_jobs/contracts/job-record.schema.json
src/audiagentic/foundation/contracts/schemas/job-record.schema.json
src/audiagentic/foundation/contracts/schema_registry.py
src/audiagentic/foundation/contracts/canonical_ids.py
src/audiagentic/components/agent_jobs/contracts/prompt-launch-request.schema.json

## Validation

Tests: event trigger creates job.json with surface=event and populated `event-source`; component/foundation schema copies both validate; correlation_id/subject round-trip; EventEnvelope timestamp mapping is explicit; timeline.ndjson first entry written via EDJ07 shared helper; existing (cli/vscode) job fixtures still validate against the extended schema; gateway-request artifact appended by EDJ05 outcome handling, not creation path.

## Effort & Risk

Complex. Job record schema may need extension for trigger provenance or gateway-request links.

## Standards

arch-standards — atomic runtime state writes, AudiaGenticError at boundary, redact sensitive detail (no raw payload dumps in provenance).
observability-standards — durable per-job timeline, event/log roles, redaction.
component-creation — job record owned by agent-jobs; gateway request record stays in agents.

## Notes

Keep ownership split: job record in agent-jobs, gateway request record in agents.
Timeline: EDJ03 records the first job timeline entries via `foundation.observability.record_timeline_event`. EDJ07 introduces the shared `job_timeline_path` helper and canonical lifecycle-event set — EDJ03's timeline writes should adopt that helper once it lands (avoid a second, divergent JSONL writer). Coordinate so the timeline path/format is defined once.
SCHEMA MIRROR (EDJ19/RV231): job-record.schema.json exists in BOTH components/agent_jobs/contracts/ and foundation/contracts/schemas/. Apply the event-source extension to both copies per the EDJ19 ownership rule (component copy authoritative, mirror byte-identical) — the EDJ19 drift test must pass after this change.

## Ledger Events

- chg_20260710_083419_event-triggered-jobs-now-carry_3537
- chg_20260710_085734_created-seven-critical-edj-rev_7918
