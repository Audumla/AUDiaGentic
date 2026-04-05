# PKT-PRV-057 — Codex structured-completion integration

**Phase:** Phase 4.11
**Status:** WAITING_ON_DEPENDENCIES
**Owner:** Codex

## Objective

Wire Codex to the shared structured-completion harness using the most stable available final
result surface, expected to be the final-message/result-file path.

## Scope

This packet owns:

- Codex completion prompt shaping
- Codex final-message/result-file parsing
- mapping Codex completion into the canonical final-result envelope
- Codex-specific smoke and integration tests

## Dependencies

- `PKT-PRV-056`
- `PKT-PRV-005`
- `PKT-PRV-032`

## Acceptance criteria

- Codex can return a deterministic structured completion payload
- direct Codex result parsing persists canonical completion artifacts without synthetic fallback when parsing succeeds
- raw result material remains available for troubleshooting

## Notes

- Codex remains wrapper-first
- this packet must not duplicate shared normalization logic owned by `PKT-PRV-056`
