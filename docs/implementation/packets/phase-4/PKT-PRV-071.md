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
