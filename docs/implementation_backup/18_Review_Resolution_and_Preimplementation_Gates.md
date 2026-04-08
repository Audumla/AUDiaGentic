# Review Resolution and Preimplementation Gates

## Purpose

Track which review issues were resolved by documentation and which are intentionally deferred to packet implementation.

## Resolved in docs

- common contract schemas and typed return values
- ledger locking and idempotency rules
- lifecycle state detection and checkpoint semantics
- approval duplicate handling and TTL
- file ownership matrix
- glossary
- prompt tag syntax frozen as `prefix-token-v1`
- prompt launch normalization boundary frozen
- `adhoc` target kind defined
- review output formalized as `ReviewReport` and `ReviewBundle`
- multi-review aggregation fixed to deterministic `all-pass`
- workflow override location standardized to `.audiagentic/project.yaml`
- .1/.2/.3/.4/.5 packet dependency sequence clarified

## Must be produced by implementation

- non-placeholder schema files with validation harness
- naming validator CLI
- lifecycle CLI stub
- ledger fixtures and idempotency tests
- Release Please managed file handling in code
- prompt parser and launcher implementation
- runtime review artifact writer and bundle aggregation logic
- CLI/VS Code adapter normalization tests
- ad hoc job subject manifest handling
- prompt shorthand and default-launch ergonomics implementation
- shared prompt-tag surface schema/descriptor updates
- provider-surface synchronization adapters and smoke tests
- provider execution compliance model and isolated per-provider implementation docs

## Deferrals

- optional server API beyond seam definition
- non-MVP session mirroring
- secret reference types beyond `env:`
- natural-language routing without tags
- automatic multi-agent fan-out from one prompt
- automatic commit/merge execution
