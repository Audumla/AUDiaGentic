# PKT-PRV-071 — Gemini structured-completion integration

**Phase:** Phase 4.11
**Status:** WAITING_ON_DEPENDENCIES
**Owner:** Gemini

## Objective

Integrate Gemini with the shared structured-completion normalization harness so prompt-triggered
Gemini runs can persist canonical AUDiaGentic final-result artifacts from bounded wrapper-driven
JSON output or a clearly-marked fallback path.

## Scope

This packet owns:

- Gemini-specific final-result extraction on top of `PKT-PRV-056`
- Gemini-specific completion prompt shaping derived from the canonical generic
  provider-function source and rendered into Gemini-facing surfaces by the shared
  regeneration facade using Gemini-owned renderer definitions
- bounded wrapper-driven JSON completion handling
- direct-versus-fallback result marking for Gemini runs
- Gemini-specific tests and fixtures proving canonical result persistence

## Dependencies

- `PKT-PRV-056`
- `PKT-PRV-006`
- `PKT-PRV-034`
- `PKT-PRV-062`
- `PKT-PRV-070`

## Acceptance criteria

- Gemini runs persist canonical normalized final-result artifacts
- direct wrapper JSON and fallback-derived output are distinguishable in the stored result
- raw stdout/stderr remain available for diagnosis
- Gemini-specific tests prove the shared normalization harness works without duplicating it
- any Gemini completion-surface rule changes are generated from the canonical generic
  provider-function source rather than hand-authored as a separate provider-only canonical
  definition

## Notes

- this packet must not duplicate shared normalization logic owned by `PKT-PRV-056`
- Gemini remains guarded until its prompt-trigger and shared-harness uplift work are further
  along, but the completion packet is defined now so later work does not require a structural
  documentation revisit
- if completion prompt shaping must change, update the canonical generic provider-function
  source and regenerate the Gemini surface output through the shared facade; do not create a
  standalone Gemini-only canonical definition for this packet
- if packet work stays strictly inside result parsing/normalization, it may proceed after
  `PKT-PRV-056`; if it requires prompt/provider-surface changes, `PKT-PRV-070` must land first

## Entry criteria

Before starting, confirm all of the following are true:

- `PKT-PRV-056` is at least `IN_PROGRESS`
- `PKT-PRV-034` remains the active Gemini prompt-trigger launch path
- `PKT-PRV-062` and `PKT-PRV-070` are available if prompt/provider-surface shaping must change
- the shared completion schema exists in `src/audiagentic/contracts/schemas/provider-completion.schema.json`
- if Gemini shared streaming uplift is required by the implementation path, coordinate with `PKT-PRV-072`

## Config, files, and artifacts

- shared completion helpers live in `src/audiagentic/streaming/completion.py`
- Gemini adapter seam: `src/audiagentic/execution/providers/adapters/gemini.py`
- generated Gemini surfaces live under `.gemini/commands/`; do not hand-edit them for packet-specific behavior
- runtime completion artifact must be written to:
  - `.audiagentic/runtime/jobs/<job-id>/completions/completion.gemini.json`

## Implementation checklist

1. identify the bounded Gemini JSON completion source available through the wrapper/adapter path
2. parse direct Gemini result data in `src/audiagentic/execution/providers/adapters/gemini.py`
3. call `normalize_provider_result()` when direct parsing succeeds
4. call `build_synthetic_fallback()` when parsing fails
5. persist the canonical artifact with `persist_completion()`
6. if prompt shaping must change, update canonical source/renderers and regenerate instead of editing generated files directly
7. add integration tests for direct parse success and fallback behavior

## Exit criteria

- Gemini writes `completion.gemini.json` using the shared schema
- direct JSON result and fallback are distinguishable in the stored artifact
- generated Gemini surfaces remain managed outputs
- no Gemini-only canonical completion contract is introduced

## Validation commands

```powershell
python -m pytest tests/integration/providers/test_gemini.py -q
python -m pytest tests/unit/streaming/test_completion.py -q
python tools/regenerate_tag_surfaces.py --project-root . --check
```
