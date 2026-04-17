# DRAFT — Secrets and CI Guidance

## Status
Draft guidance only. Not a blocking MVP contract.

## MVP rule
- tracked project config stores secret references only
- supported secret reference syntax in MVP: `env:NAME`
- CI pipelines should inject provider secrets through the CI secret store into environment variables at runtime

## Local development guidance
- export required provider variables in the local shell or IDE run configuration
- do not commit example files containing real secret values

## CI guidance
- map CI secret names to the required `env:` references
- validate presence at runtime before provider use
- fail fast with a clear missing-reference message that does not reveal secret values

## Deferred enhancements
- vault-backed secret references
- rotation and secret provenance tracking
- per-project secret profiles
