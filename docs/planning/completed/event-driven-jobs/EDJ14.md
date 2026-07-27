---
id: EDJ14
order: 85
plan: event-driven-jobs
state: completed
validate-first: true
priority: P2
work: S
created-by: claude
---

# Trigger firing audit and event-jobs operator overview

## Description

REMAINDER ONLY: trigger-audit writing landed. Implement one read-only, on-demand operator aggregation surface over existing records; do not change the audit writer or add counters/metrics.

## Steps

1. Create `event_overview.py` with public `event_jobs_overview(project_root: Path) -> dict[str, Any]`. It is the only new aggregation module; `event_observer.py` remains writer-only.
2. Read `.audiagentic/runtime/agent-jobs/trigger-audit.ndjson` using `foundation.io.load_ndjson` and read job records through the existing jobs-store list API. Missing/unreadable optional audit/jobs paths return empty aggregates after logger.warning with `exc_info=True`; never raise for absent runtime state.
3. Return this exact stable shape: `{by_trigger: dict[str, {fired: int, suppressed: int, failed: int}], jobs_by_state: dict[str, int], recent_failures: list[dict]}`. Aggregate actual writer fields `trigger_id`, `status`, `job_id`, `correlation_id`, `event_type`, `error_code`, `error_message`; ignore malformed/unknown statuses. `jobs_by_state` includes only records with event provenance using the actual persisted launch-source/event-source field discovered in `build_job_from_event`; add characterization fixture before choosing field.
4. `recent_failures` uses records where `status == "failed"`, newest timestamp first, max 5. Each entry has only `{trigger_id, event_type, correlation_id, error_code, error_message}`; use shared redaction/summarization before returning error_message. Never return payloads, prompts, metadata, or raw record objects.
5. Add one no-parameter read-only MCP wrapper on existing agent-jobs MCP server. Wrapper gets root only via `project_root_from_env()` and returns the exact overview dict. Follow existing `agent_llm_gateway_overview` construction; no server/bootstrap duplication.
6. Tests assert literal shape for empty, normal, malformed, and missing-file cases; status—not obsolete `outcome`—drives counts.

## Files

src/audiagentic/components/agent_jobs/event_overview.py
src/audiagentic/components/agent_jobs/event_observer.py (read-only: audit path/shape)
tests/unit/jobs/test_event_overview.py

## Validation

Unit tests: aggregates fixture audit file into correct per-trigger outcome counts; jobs_by_state counts only event-origin jobs; recent_failures capped at 5, redacted, newest first; absent audit file and absent jobs dir return empty structures without error; MCP tool registered and returns the same shape.

## Effort & Risk

Medium. Deliberately thin: one ndjson + one aggregation function + one read-only surface. Anything beyond (dashboards, metrics export, alerting) is future work reading the same records.

## Standards

observability-standards — durable audit record, redaction, event/log roles.
arch-standards — AudiaGenticError at boundary; atomic appends.

## Notes

Narrowed per RV252 — the audit-writing half shipped with EDJ02/EDJ20. Audit record shape is now owned by the implemented writer in event_observer.py; do not change it here, only read it.

## Ledger Events

- chg_20260712_051854_make-event-driven-job-work-ite_9726
- chg_20260712_054608_operators-can-now-get-an-on-de_1317
