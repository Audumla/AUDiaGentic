---
id: EDJ24
order: 64
plan: plan-event-driven-jobs
state: completed
validate-first: true
priority: P1
work: S
created-by: claude
---

# Redact dead-letter and audit record content (structural summarizer)

## Description

RV249 confirmed: event_observer.py writes payload_summary = str(payload)[:500] (lines ~230 and ~544) and the raw metadata dict into dead-letter.ndjson. dead_letter.py only caps length; append_operational_record's denylist only checks TOP-LEVEL field names. A malformed event payload containing prompt-body / api_key / tokens is serialized verbatim — violating EDJ12's redaction contract and arch-standards §8. Fix by building ONE structural summarizer on the existing shared redaction primitive (foundation/logging/redaction.py, built by RS16) — do NOT fork a second redaction implementation (same rule OU01 follows for stdout sites).

## Steps

1. Extend only `foundation/logging/redaction.py`; it remains sole sensitive-key/pattern owner. Add one exported `summarize_structure(value: Any, *, max_len: int = 500) -> str`. It never raises and returns deterministic compact JSON (`json.dumps(..., sort_keys=True, default=str)`) or a redacted/truncated fallback string.
2. Recursive transform rules: sensitive key matching is case-insensitive and uses one compiled key pattern covering `prompt`, `key`, `token`, `secret`, `password`, `authorization`, `output`, and `auth`; sensitive values become `[REDACTED]`. Non-sensitive strings pass through `redact_text` then truncate to 80 characters. Traverse at most depth 8 and first 20 dict/list entries; append `[TRUNCATED]` sentinel for omitted content. Apply final `truncate_output`/hard cap so output length never exceeds max_len. Never emit raw secret-shaped leaf values.
3. Add `safe_metadata(metadata)` in same module returning only `{correlation_id, correlation-id, subject, job-id, trigger-id, source-component}` with recursively redacted values; do not define a second local allowlist in agent-jobs.
4. Replace both event_observer raw `str(payload)[:500]` sites with `summarize_structure(payload)` and both raw metadata dead-letter values with `safe_metadata(metadata)`. Do not alter gateway payloads or job records.
5. In `append_operational_record`, recursively inspect all mapping keys/list values before timestamp mutation. Raise existing `CON-OPR-002` for a denylisted nested key; its denylist imports/reuses the redaction module matcher rather than carrying a parallel pattern set. Do not inspect string contents there—callers summarize/redact values.
6. Tests assert raw ndjson never contains nested secret values, JSON summary deterministic/bounded/depth-safe, unknown metadata absent, nested denylisted key rejected, and benign nested values persist.

## Files

src/audiagentic/foundation/logging/redaction.py
src/audiagentic/components/agent_jobs/event_observer.py
src/audiagentic/foundation/observability/operational_records.py
tests/unit/foundation/test_redaction.py
tests/unit/jobs/test_event_observer.py

## Validation

Tests: a payload containing {'prompt-body': 'SECRET_PROMPT', 'api_key': 'sk-123', 'nested': {'token': 'tkn'}} dead-letters WITHOUT any of those values appearing anywhere in dead-letter.ndjson (assert on raw file text); metadata whitelist drops unexpected keys; summarize_structure output bounded at max_len for pathological inputs (deep nesting, huge lists); recursive denylist in append_operational_record rejects nested prompt-body with CON-OPR-002; existing redaction tests green (pattern set still single-sourced).

## Effort & Risk

Simple-mid. The one design rule: the pattern set lives ONLY in foundation/logging/redaction.py (RS16/OU01 doctrine) — extending it there benefits every consumer; no local regex lists in agent_jobs or observability.

## Standards

arch-standards — §8 redaction: no raw prompts/keys/tokens in persisted error details.
observability-standards — sidecar records redacted; single shared redaction primitive.

## Notes

From review RV249 (codex). Cross-plan coordination: output-redaction/OU01 fans the same primitive out to stdout/stderr capture sites — this item adds the structural-summarizer face of that primitive; both consume, neither forks. Noted in OU01.

## Ledger Events

- chg_20260712_051854_make-event-driven-job-work-ite_9726
- chg_20260712_053400_dead-letter-and-audit-records_5441
