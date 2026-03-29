# Destructive Test Sandbox

## Purpose

Define how install/update/cutover/uninstall tests run safely without touching a developer's real repository.

## Sandbox strategy

Use **ephemeral sandbox repositories** under a unique temp root for every destructive test.

## Sandbox layout

```text
<tmp>/sandbox-<test-id>/
  repo/
    .git/
    docs/
    .audiagentic/
  logs/
  artifacts/
```

## Required rules

1. Never run destructive tests against the working tree.
2. Use a fresh sandbox per test case.
3. Verify cleanup behavior as part of the test.
4. Preserve failed sandboxes only when `KEEP_FAILED_SANDBOX=1`.
5. Run parallel destructive tests only when their sandboxes are isolated.

## Required helper surface

- `tools/create_sandbox.py`
- `tests/helpers/sandbox.py`

## DRAFT future enhancements

- container-backed sandboxes
- snapshot/restore harness
- OS matrix sandbox verification
