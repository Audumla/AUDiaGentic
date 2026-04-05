# PKT-PRV-068 — Claude structured-completion integration

**Phase:** Phase 4.11
**Status:** WAITING_ON_DEPENDENCIES
**Owner:** Claude

## Objective

Integrate Claude with the shared structured-completion normalization harness so prompt-triggered
Claude runs produce canonical AUDiaGentic final-result artifacts without depending on synthetic
fallback review bundles when direct completion data is available.

## Scope

This packet owns:

- Claude-specific final-result extraction on top of `PKT-PRV-056`
- Claude-specific completion prompt shaping derived from the canonical generic
  provider-function source and rendered into Claude surfaces by the shared regeneration
  facade using Claude-owned renderer definitions
- hook-backed or wrapper-bounded JSON completion handling
- direct-versus-fallback result marking for Claude runs
- Claude-specific tests and fixtures proving canonical result persistence

## Dependencies

- `PKT-PRV-056`
- `PKT-PRV-004`
- `PKT-PRV-033`
- `PKT-PRV-055`
- `PKT-PRV-062`
- `PKT-PRV-070`

## Acceptance criteria

- Claude runs persist canonical normalized final-result artifacts
- direct provider JSON and wrapper-derived fallback are distinguishable in the stored result
- raw stdout/stderr remain available for diagnosis
- Claude-specific tests prove the shared normalization harness works without duplicating it
- any Claude completion-surface rule changes are generated from the canonical generic
  provider-function source rather than hand-authored as a separate provider-only canonical
  definition

## Notes

- this packet must not duplicate shared normalization logic owned by `PKT-PRV-056`
- wrapper fallback remains mandatory even when hook-backed JSON completion is available
- if completion prompt shaping must change, update the canonical generic provider-function
  source and regenerate the Claude surface output through the shared facade; do not create a
  standalone Claude-only canonical definition for this packet
- if packet work stays strictly inside result parsing/normalization, it may proceed after
  `PKT-PRV-056`; if it requires prompt/provider-surface changes, `PKT-PRV-070` must land first
