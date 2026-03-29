# Error Envelope and Error Codes

## Purpose

Provide the canonical machine-readable error contract used by CLI tools, lifecycle operations, release scripts, jobs, providers, and overlays.

## ErrorEnvelope

```json
{
  "contract-version": "v1",
  "ok": false,
  "error-code": "RLS-VALIDATION-001",
  "error-kind": "validation",
  "message": "release fragment payload is invalid",
  "details": {
    "field": "event-id"
  }
}
```

## Error kinds

- `validation`
- `business-rule`
- `io`
- `external`
- `internal`

## Code prefixes

- `FND-*` foundation/contracts
- `LFC-*` lifecycle
- `RLS-*` release
- `JOB-*` jobs
- `PRV-*` providers
- `DSC-*` Discord
- `MIG-*` migration

## Rules

- JSON-capable tools must emit this envelope on failure
- human-readable stderr may accompany the envelope but must not contradict it
- success envelopes are not required in MVP; success output may be command-specific
- secret material must never be included in `message` or `details`

## DRAFT future enhancements

- machine-readable warning envelope
- correlation ids across nested commands
- richer nested error chains
