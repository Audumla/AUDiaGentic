---
id: EDJ07
order: 90
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P2
complexity: mid
---

# Standardize agent-jobs timelines and lifecycle events

## Description

Bring agent-jobs observability up to the new standard by writing per-job `timeline.ndjson` and publishing job lifecycle events. Replace or align ad hoc control-events logging with the shared foundation observability helper.

## Steps

1. Add `job_timeline_path` helper.
2. Record job created/ready/running/completed/failed/cancelled and control requested/applied/ignored milestones.
3. Publish job lifecycle events with subject metadata.
4. Keep existing control-events compatibility if needed, but make timeline canonical.

## Files

src/audiagentic/components/agent_jobs/paths.py
src/audiagentic/components/agent_jobs/control.py
src/audiagentic/components/agent_jobs/state_machine.py
src/audiagentic/components/agent_jobs/events.py

## Validation

Tests that job state transitions and control requests append timeline entries and lifecycle events include job id/correlation id.

## Effort & Risk

Medium. Need avoid duplicate/conflicting logs while preserving compatibility for existing tests/tools.

## Standards



## Notes

Use `foundation.observability.record_timeline_event`; no component-local JSONL writer for new paths.
Overlaps EDJ03 step 3 (which writes the first job timeline entries). This item owns the canonical `job_timeline_path` helper and lifecycle-event set; EDJ03 should consume that helper rather than defining its own path/format. Define timeline path + entry shape once, here, and have EDJ03 adopt it.
