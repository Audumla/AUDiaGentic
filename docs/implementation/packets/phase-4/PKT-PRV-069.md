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
