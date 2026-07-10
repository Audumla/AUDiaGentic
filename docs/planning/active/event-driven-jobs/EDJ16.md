---
id: EDJ16
order: 92
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P1
complexity: mid
created-by: codex
---

# Add shared observable append-only record helper for dead-letter and trigger audit

## Description

Provide one reusable foundation primitive for durable append-only operational sidecar records used by event-driven jobs: dead-letter entries (EDJ12) and trigger firing audit entries (EDJ14). Avoid component-local duplicate ndjson writers, ad hoc locking, and inconsistent redaction/correlation fields.

## Steps

1. Add a foundation helper beside observability or IO for append-only observable records, reusing `atomic_write_ndjson` only if it is hardened for concurrent append semantics.
2. Include per-path locking or another safe write strategy consistent with `record_timeline_event`.
3. Define required fields: contract-version, timestamp, component, resource-kind or record-kind, correlation-id, event/outcome, and redacted attributes.
4. Update OBSERVABILITY_STANDARDS.md to distinguish resource timelines from operational sidecar records and require shared helper usage for new durable audit/dead-letter streams.
5. Refactor EDJ12 dead-letter writer and EDJ14 trigger audit writer plans to consume this helper, not create separate JSONL writers.

## Files

src/audiagentic/foundation/observability/*
src/audiagentic/foundation/io.py
docs/standards/OBSERVABILITY_STANDARDS.md
src/audiagentic/components/agent_jobs/dead_letter.py
src/audiagentic/components/agent_jobs/event_observer.py

## Validation

Unit tests for append, absent parent creation, parseable ndjson, concurrent per-path writes, redaction expectations, correlation-id propagation, and consumers in EDJ12/EDJ14 using the shared helper. Architecture grep/test should fail on new component-local ndjson append helpers for agent-jobs audit/dead-letter paths.

## Effort & Risk

Medium. Risk is adding too much event-store infrastructure; keep this to a tiny append-only helper and a standard paragraph.

## Standards



## Notes



## Ledger Events


