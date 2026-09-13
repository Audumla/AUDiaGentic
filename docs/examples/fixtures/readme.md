# Fixtures

This folder contains example valid and invalid fixtures used by the schema
validator and release/acceptance tests.

## Naming and use

- `*.valid.*` fixtures must satisfy the corresponding schema or contract.
- `*.invalid.*` fixtures intentionally exercise rejection paths and must not
  be used as production examples.
- `*.sample.*` files are renderer/input examples. They are illustrative unless
  a test explicitly names them.
- `legacy-changelog.sample.md` is retained only as a historical migration
  fixture; it is not the current changelog format.
- `CURRENT_RELEASE.sample.md` is the canonical current-release sample. Keep a
  single casing for this filename because Windows filesystems are commonly
  case-insensitive.

The JSON and YAML fixtures in this directory are consumed by tests under
`tests/unit/contracts/` and `tests/integration/release/`. When a contract
changes, update the schema, the appropriate valid/invalid pair, and the
consuming tests together.
