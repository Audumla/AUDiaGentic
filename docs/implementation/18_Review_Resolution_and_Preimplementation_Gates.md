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

## Must be produced by implementation

- non-placeholder schema files with validation harness
- naming validator CLI
- lifecycle CLI stub
- ledger fixtures and idempotency tests
- Release Please managed file handling in code

## Deferrals

- optional server API beyond seam definition
- non-MVP session mirroring
- secret reference types beyond `env:`
