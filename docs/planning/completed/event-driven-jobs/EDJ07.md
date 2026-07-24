---
id: EDJ07
order: 55
plan: plan-event-driven-jobs
state: completed
validate-first: true
priority: P2
work: M
---

# Standardize agent-jobs timelines and lifecycle events

## Description

Bring agent-jobs observability up to the new standard by writing per-job `timeline.ndjson` and publishing job lifecycle events. Replace or align ad hoc control-events logging with the shared foundation observability helper.

## Steps

1. Add `job_timeline_path` helper in paths.py; timeline is per-job `timeline.ndjson` written via `foundation.observability.record_timeline_event`.
2. Define the canonical, namespaced timeline event-name set in ONE module-level tuple so later monitoring can enumerate it without parsing code: `job.created`, `job.ready`, `job.running`, `job.awaiting-approval`, `job.completed`, `job.failed`, `job.cancelled`, `job.control.requested`, `job.control.applied`, `job.control.ignored`, `job.dispatch.accepted`, `job.dispatch.rejected`, `job.gateway-outcome-received`, `job.state-propagated`. New names must extend this tuple — additive only, never rename (downstream monitoring keys on them).
3. Every timeline entry carries: `job-id`, `correlation_id`, and where relevant `trigger-id` / `request-id` as attributes — this is the join key set for cross-record tracing (job timeline <-> gateway timeline <-> event log).
4. Publish job lifecycle events with subject metadata mirroring the timeline milestones.
5. Keep existing control-events compatibility if needed, but timeline is canonical.

## Files

src/audiagentic/components/agent_jobs/paths.py
src/audiagentic/components/agent_jobs/control.py
src/audiagentic/components/agent_jobs/state_machine.py
src/audiagentic/components/agent_jobs/events.py

## Validation

Tests: each state transition and control request appends exactly one timeline entry with the canonical name; lifecycle events include job id/correlation id; the event-name tuple covers every name written anywhere in agent_jobs (grep-style test); entries for event-triggered jobs include trigger-id.

## Effort & Risk

Medium. Need avoid duplicate/conflicting logs while preserving compatibility for existing tests/tools.

## Standards

observability-standards — durable per-resource timeline as canonical record; event vs log roles; redaction; use foundation.observability.record_timeline_event (no component-local JSONL writer for new paths).
arch-standards — atomic appends, AudiaGenticError at boundary.

## Notes

Use `foundation.observability.record_timeline_event`; no component-local JSONL writer for new paths. Extendability is deliberate and cheap: stable namespaced names + stable join keys (job-id/correlation_id/trigger-id/request-id) are what allow richer monitoring (EDJ14 overview, future metrics) to be layered on later without touching this code again. Do not build metrics/aggregation here.

## Ledger Events

- chg_20260710_083120_agent-jobs-now-emit-structured_1726
