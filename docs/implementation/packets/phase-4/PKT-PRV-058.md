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
