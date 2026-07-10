---
id: EDJ20
order: 34
plan: plan-event-driven-jobs
state: pending
validate-first: true
priority: P2
complexity: simple
created-by: claude
---

# Shared append-only operational record helper (sidecar ndjson)

## Description

From RV230: EDJ12 (dead-letter.ndjson) and EDJ14 (trigger-audit.ndjson) both introduce append-only operational sidecar records, but current primitives don't fit: foundation.observability.record_timeline_event is per-resource timelines; foundation.io.atomic_write_ndjson(append=True) rewrites the whole file per append (O(n) growth) and has no per-path lock. Provide ONE small foundation helper both items call, so writer/locking/redaction logic exists once.

## Steps

1. Add `append_operational_record(path, record)` to foundation (observability module or io): true O(1) append (open 'a', write line, flush/fsync) guarded by a per-path threading lock registry; creates parent dirs; injects `timestamp` if absent.
2. Enforce the common envelope at the helper boundary: caller supplies record; helper requires `correlation_id` key present (may be null) and rejects records containing obviously-unredacted fields per a small denylist (e.g. `prompt-body`, `output`) — keep this a cheap guard, not a schema.
3. Update OBSERVABILITY_STANDARDS.md: distinguish timelines (per-resource history via record_timeline_event) from operational sidecar records (cross-cutting append-only ndjson via this helper); both require correlation fields and redaction.
4. EDJ12's dead-letter writer and EDJ14's trigger-audit writer call this helper — no bespoke ndjson writing in either.

## Files

src/audiagentic/foundation/observability.py
docs/standards/OBSERVABILITY_STANDARDS.md
tests/unit/foundation/test_operational_records.py

## Validation

Unit tests: concurrent appends from threads produce no interleaved/corrupt lines; timestamp injected; missing correlation_id rejected; denylisted field rejected; file created with parents; load_ndjson round-trips. EDJ12/EDJ14 tests exercise their records through this helper.

## Effort & Risk

Simple. One function + one lock registry + standard paragraph. Do NOT build rotation, retention, or a record framework — append + guard only. Multi-process locking is out of scope (same single-process reality as the gateway queue; note it for EDJ13).

## Standards

observability-standards — timelines vs operational records, redaction, correlation keys.
arch-standards — atomic/durable writes, AudiaGenticError at boundary, registered error codes.

## Notes

From review RV230 (codex). EDJ12 and EDJ14 now depend on this item for their writers; it should land before or with EDJ12.

## Ledger Events


