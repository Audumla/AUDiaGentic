---
id: EDJ12
order: 36
plan: plan-event-driven-jobs
state: completed
validate-first: true
priority: P2
work: M
created-by: claude
---

# Define async event-handling error standard: retry, dead-letter, replay

## Description

Guideline gap: ARCHITECTURE_STANDARDS §8 covers synchronous error handling (AudiaGenticError, code registration, redaction) but no standard defines failure handling for ASYNC event-driven work — what happens when a bus handler fails, a dispatch event cannot be published, or a lifecycle outcome cannot be applied. EDJ02/EDJ04/EDJ05 all need this. Define the standard, then implement the minimal v1 capability agent-jobs needs.

## Steps

1. Add an 'Async event handling' section to ARCHITECTURE_STANDARDS.md (or a new focused standard doc if it exceeds ~1 page) covering:
   - handlers never raise out of the bus (isolation rule already practiced in agents_gateway_queue._publish_lifecycle_event — codify it)
   - retry policy: v1 default is NO automatic retry for trigger firings (an LLM job is not safely idempotent); retries must be explicit and idempotency-keyed
   - dead-letter: any failed firing/dispatch/outcome-application is recorded durably with {event-type, payload-summary (redacted), metadata, trigger-id/job-id, error, timestamp}
   - replay: dead-letter entries must carry enough to re-fire manually; automatic replay is out of scope v1
2. Implement minimal v1: `agent_jobs/dead_letter.py` defining the dead-letter record shape and writing via the shared `append_operational_record` helper from EDJ20 — NO bespoke ndjson writer here. Used by EDJ02 step 5, EDJ04 step 5, EDJ05 notes.
3. Register dead-letter-related error codes in agent-jobs error-resolutions.yaml.
4. Cross-link from OBSERVABILITY_STANDARDS (dead-letter is an operational sidecar record per EDJ20's timelines-vs-operational-records distinction).

## Files

docs/standards/ARCHITECTURE_STANDARDS.md
docs/standards/OBSERVABILITY_STANDARDS.md
src/audiagentic/components/agent_jobs/dead_letter.py

## Validation

Standard section reviewed and merged; unit tests: failed handler writes one redacted dead-letter entry with correlation context; entry round-trips (parseable, contains re-fire inputs); no raw payload/prompt in entries; codes registered.

## Effort & Risk

Medium. Keep the standard one page and the v1 capability one small module — the point is a defined contract, not infrastructure. Automatic retry/replay is explicitly deferred.

## Standards

arch-standards — §8 error codes/registration/redaction extended, not duplicated.
observability-standards — dead-letter as durable observable record.

## Notes

Called out during 2026-07-10 critical review: EDJ02/04/05 each referenced failure handling with no governing guideline. This item owns the dead-letter record format those items write. Depends on EDJ20 (RV230) for the shared append-only writer — EDJ20 lands first or together.

## Ledger Events

- chg_20260710_080144_added-async-event-handling-err_4286
- chg_20260710_085734_created-seven-critical-edj-rev_7918
