# PKT-PRV-058 — Cline structured-completion integration

**Phase:** Phase 4.11
**Status:** WAITING_ON_DEPENDENCIES
**Owner:** Codex

## Objective

Wire Cline to the shared structured-completion harness using the most stable available final
result surface, expected to be JSON returned through the `cline --json` completion path.

## Scope

This packet owns:

- Cline completion prompt shaping
- Cline final completion parsing
- mapping Cline completion into the canonical final-result envelope
- Cline-specific smoke and integration tests

## Dependencies

- `PKT-PRV-056`
- `PKT-PRV-009`
- `PKT-PRV-037`

## Acceptance criteria

- Cline can return a deterministic structured completion payload
- direct Cline result parsing persists canonical completion artifacts without synthetic fallback when parsing succeeds
- raw result material remains available for troubleshooting

## Notes

- Cline remains the first-wave provider for stdout/NDJSON completion normalization
- this packet must not duplicate shared normalization logic owned by `PKT-PRV-056`

## Entry criteria

Before starting, confirm all of the following are true:

- `PKT-PRV-056` is at least `IN_PROGRESS`
- `PKT-PRV-037` is at least `READY_FOR_REVIEW`
- Cline runs already persist standard runtime artifacts successfully
- the shared completion schema exists in `src/audiagentic/contracts/schemas/provider-completion.schema.json`

## Config, files, and artifacts

- shared completion helpers live in `src/audiagentic/streaming/completion.py`
- runtime completion artifact must be written to:
  - `.audiagentic/runtime/jobs/<job-id>/completions/completion.cline.json`
- if prompt shaping changes are required, use canonical skill/provider-surface inputs rather than hand-editing generated provider files

## Implementation checklist

1. identify the most stable Cline completion payload already available from stdout or NDJSON output
2. parse direct Cline result data in `src/audiagentic/execution/providers/adapters/cline.py`
3. call `normalize_provider_result()` when direct parsing succeeds
4. call `build_synthetic_fallback()` only when direct parsing fails
5. persist the canonical artifact with `persist_completion()`
6. add integration tests for direct parse success and fallback behavior

## Exit criteria

- Cline writes `completion.cline.json` using the shared schema
- direct parse and fallback are distinguishable in the stored artifact
- raw stdout/stderr remain available for troubleshooting
- no Cline-only completion schema or persistence path is introduced

## Validation commands

```powershell
python -m pytest tests/integration/providers/test_cline.py -q
python -m pytest tests/unit/streaming/test_completion.py -q
```
