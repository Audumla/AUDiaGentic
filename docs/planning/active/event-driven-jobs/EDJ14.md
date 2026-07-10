---
id: EDJ14
order: 85
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P2
complexity: mid
created-by: claude
---

# Trigger firing audit and event-jobs operator overview

## Description

Operator-facing observability for event-driven jobs, mirroring the proven gateway_overview() pattern: a durable per-trigger firing audit plus an aggregate overview so 'what have my triggers been doing' is answerable without reading individual job records. Capable today from timeline/audit records; extendable later (metrics export, richer monitors) because it reads stable names/keys defined in EDJ07 — no new instrumentation surface.

## Steps

1. Durable firing audit: EDJ02 writes one entry per trigger match (fired / suppressed / failed) to trigger-audit.ndjson with {trigger-id, event-type, outcome, job-id?, correlation_id, timestamp} — this item owns the record shape; the write goes through the shared `append_operational_record` helper from EDJ20 (no bespoke ndjson writer).
2. Add `event_jobs_overview(project_root)` in agent-jobs: counts by trigger-id and outcome, jobs by state for event-origin jobs (launch-source.surface == 'event'), recent failures (last 5 with error summary + correlation_id) — same shape philosophy as agents_gateway_api.gateway_overview.
3. Expose via the existing agent-jobs MCP/status surface (follow how gateway_overview is exposed; read-only).
4. Extendability rule (documented, not built): richer monitoring layers on the audit file + EDJ07 timeline names + join keys (job-id/correlation_id/trigger-id/request-id); no metrics framework, counters DB, or polling daemon in v1.

## Files

src/audiagentic/components/agent_jobs/event_observer.py
src/audiagentic/components/agent_jobs/paths.py
docs/standards/OBSERVABILITY_STANDARDS.md

## Validation

Unit tests: each firing outcome appends exactly one audit entry with correlation context; overview aggregates counts by trigger/outcome and job state correctly from fixtures; recent-failures redacted (no prompts/payloads); overview works when audit file absent (empty result, no error).

## Effort & Risk

Medium. Deliberately thin: one ndjson + one aggregation function + one read-only surface. Anything beyond (dashboards, metrics export, alerting) is future work reading the same records.

## Standards

observability-standards — durable audit record, redaction, event/log roles.
arch-standards — AudiaGenticError at boundary; atomic appends.

## Notes

Called out during 2026-07-10 critical review: monitoring must be capable today and extendable later. Depends on EDJ02 (writes audit), EDJ07 (canonical names/keys), and EDJ20 (shared operational-record writer, RV230).

## Ledger Events


