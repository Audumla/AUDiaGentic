---
id: EDJ07
order: 55
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

1. Add `job_timeline_path` helper in `paths.py`; this item lands before EDJ03 so initial event-trigger job creation uses canonical timeline paths.
2. Define canonical lifecycle/milestone event constants in `agent_jobs/events.py`, including job state events and prompt/dispatch/gateway milestones.
3. Publish job lifecycle events with subject metadata and correlation id using the pattern from `components/planning/events.py` (best-effort publish through `get_bus().publish()`).
4. Clarify timeline ownership: state transitions should record state lifecycle entries inside `state_machine.py`/transition helper; callers record non-state milestones (prompt-rendered, dispatch-requested, gateway-linked, etc.).
5. Record job created/ready/running/completed/failed/cancelled and control requested/applied/ignored milestones.
6. Include prompt assembly milestones: template-loaded, context-built, prompt-rendered, dispatch-requested, gateway-linked. Redact prompt body; store prompt source and context key names only.
7. Audit `control.py` current control-event/log behavior and migrate/align it to timeline entries while preserving compatibility for existing tests/tools.
8. Keep existing control-events compatibility if needed, but make timeline canonical.
9. Document single-writer-per-job-directory assumption or add file-level locking if multi-process writes are supported.

## Files

src/audiagentic/components/agent_jobs/paths.py
src/audiagentic/components/agent_jobs/control.py
src/audiagentic/components/agent_jobs/state_machine.py
src/audiagentic/components/agent_jobs/events.py

## Validation

Tests that job state transitions and control requests append timeline entries and lifecycle events include job id/correlation id. Tests for lifecycle topic constants, best-effort event publish behavior, prompt/dispatch milestone redaction, control.py compatibility, and concurrent writer assumption/locking behavior.

## Effort & Risk

Medium. Need avoid duplicate/conflicting logs while preserving compatibility for existing tests/tools.

## Standards

observability-standards — durable per-resource timeline as canonical record; event vs log roles; redaction; use foundation.observability.record_timeline_event (no component-local JSONL writer for new paths).
arch-standards — atomic appends, AudiaGenticError at boundary.

## Notes

Use `foundation.observability.record_timeline_event`; no component-local JSONL writer for new paths.
Overlaps EDJ03 step 3 (which writes the first job timeline entries). This item owns the canonical `job_timeline_path` helper and lifecycle-event set; EDJ03 should consume that helper rather than defining its own path/format. Define timeline path + entry shape once, here, and have EDJ03 adopt it.
