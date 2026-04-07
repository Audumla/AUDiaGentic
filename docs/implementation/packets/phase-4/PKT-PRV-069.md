# PKT-PRV-069 — opencode structured-completion integration

**Phase:** Phase 4.11
**Status:** WAITING_ON_DEPENDENCIES
**Owner:** opencode

## Objective

Integrate opencode with the shared structured-completion normalization harness so tagged
opencode runs persist canonical AUDiaGentic final-result artifacts from CLI JSON output or a
clearly-marked wrapper-derived fallback.

## Scope

This packet owns:

- opencode-specific final-result extraction on top of `PKT-PRV-056`
- opencode-specific completion prompt shaping derived from the canonical generic
  provider-function source and rendered into opencode-facing surfaces by the shared
  regeneration facade using opencode-owned renderer definitions
- direct JSON line parsing and fallback result shaping for opencode runs
- direct-versus-fallback result marking for opencode runs
- opencode-specific tests and fixtures proving canonical result persistence

## Dependencies

- `PKT-PRV-056`
- `PKT-PRV-064`
- `PKT-PRV-067`
- `PKT-PRV-062`
- `PKT-PRV-070`

## Acceptance criteria

- opencode runs persist canonical normalized final-result artifacts
- direct CLI JSON and wrapper-derived fallback are distinguishable in the stored result
- raw stdout/stderr remain available for diagnosis
- opencode-specific tests prove the shared normalization harness works without duplicating it
- any opencode completion-surface rule changes are generated from the canonical generic
  provider-function source rather than hand-authored as a separate provider-only canonical
  definition

## Notes

- this packet must not duplicate shared normalization logic owned by `PKT-PRV-056`
- direct JSON output is preferred, but fallback normalization must remain explicit and stable
- if completion prompt shaping must change, update the canonical generic provider-function
  source and regenerate the opencode surface output through the shared facade; do not create
  a standalone opencode-only canonical definition for this packet
- if packet work stays strictly inside result parsing/normalization, it may proceed after
  `PKT-PRV-056`; if it requires prompt/provider-surface changes, `PKT-PRV-070` must land first

## Entry criteria

Before starting, confirm all of the following are true:

- `PKT-PRV-056` is at least `IN_PROGRESS`
- `PKT-PRV-064` and `PKT-PRV-067` are stable enough that opencode execution/bridge paths are reviewable
- `PKT-PRV-062` and `PKT-PRV-070` are available if prompt/provider-surface shaping must change
- the shared completion schema exists in `src/audiagentic/contracts/schemas/provider-completion.schema.json`

## Config, files, and artifacts

- shared completion helpers live in `src/audiagentic/streaming/completion.py`
- opencode adapter seam: `src/audiagentic/execution/providers/adapters/opencode.py`
- generated opencode surfaces live under `.opencode/skills/`; do not hand-edit them for packet-specific behavior
- runtime completion artifact must be written to:
  - `.audiagentic/runtime/jobs/<job-id>/completions/completion.opencode.json`

## Implementation checklist

1. parse direct opencode JSON result data in `src/audiagentic/execution/providers/adapters/opencode.py`
2. call `normalize_provider_result()` when direct parsing succeeds
3. call `build_synthetic_fallback()` when parsing fails
4. persist the canonical artifact with `persist_completion()`
5. if prompt shaping must change, update canonical source/renderers and regenerate instead of editing generated files directly
6. add integration tests for direct parse success and fallback behavior

## Exit criteria

- opencode writes `completion.opencode.json` using the shared schema
- direct JSON result and fallback are distinguishable in the stored artifact
- generated opencode surfaces remain managed outputs
- no opencode-only canonical completion contract is introduced

## Validation commands

```powershell
python -m pytest tests/integration/providers/test_opencode.py -q
python -m pytest tests/unit/streaming/test_completion.py -q
python tools/regenerate_tag_surfaces.py --project-root . --check
```
