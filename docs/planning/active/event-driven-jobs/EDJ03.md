---
id: EDJ03
order: 60
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P1
complexity: complex
---

# Create durable job records from event triggers

## Description

When a configured trigger fires, create a durable agent job record that captures trigger provenance, event metadata, target, workflow profile, and rendered instructions. Link the job to downstream gateway requests so operators can trace job -> agent execution.

## Steps

1. Extend job launch/build path or add a trigger-specific builder for event-origin jobs.
2. Persist launch source with event type, trigger id, correlation id, subject, and source component.
3. Record a job timeline using `foundation.observability.record_timeline_event`.
4. Store downstream gateway request id(s) as job artifacts or launch metadata without moving gateway records into agent-jobs.

## Files

src/audiagentic/components/agent_jobs/records.py
src/audiagentic/components/agent_jobs/jobs_store.py
src/audiagentic/components/agent_jobs/prompt_launch.py
src/audiagentic/components/agent_jobs/paths.py

## Validation

Tests that event trigger creates job.json, launch metadata, timeline.ndjson, and preserves correlation_id/subject.

## Effort & Risk

Complex. Job record schema may need extension for trigger provenance or gateway-request links.

## Standards



## Notes

Keep ownership split: job record in agent-jobs, gateway request record in agents.
Timeline: EDJ03 records the first job timeline entries via `foundation.observability.record_timeline_event`. EDJ07 introduces the shared `job_timeline_path` helper and canonical lifecycle-event set — EDJ03's timeline writes should adopt that helper once it lands (avoid a second, divergent JSONL writer). Coordinate so the timeline path/format is defined once.
