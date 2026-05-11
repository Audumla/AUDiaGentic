# Stage 0 acceptance criteria

Stage 0 is accepted when all of these are true:

## Goose binary

- `fetch-goose.sh` / `fetch-goose.ps1` downloads Goose into `.audiagentic/provisioning/goose/bin/`.
- The Goose binary is executable.
- No Goose binary is tracked by git.

## Model endpoint

- The configured endpoint responds to an OpenAI-compatible chat request.
- Default endpoint: `http://10.10.200.52:13305/v1` (llama-swap).
- Model name configurable with `GOOSE_MODEL` (default: `qwen3.5-2b`).

## Smoke test

Running from repo root:

```bash
src/audiagentic/provisioning/harness/goose/scripts/smoke-test.sh
# or
src/audiagentic/provisioning/harness/goose/scripts/smoke-test.ps1
```

Output includes:

```text
audiagentic-goose-local-ok
```

## Interactive session

```bash
src/audiagentic/provisioning/harness/goose/scripts/run-goose.sh .
# or
src/audiagentic/provisioning/harness/goose/scripts/run-goose.ps1
```

Starts a Goose session using the local model.

## Isolation

- Runtime files: `.audiagentic/provisioning/goose/bin/` and `.audiagentic/runtime/goose/`.
- Source-controlled files: `src/audiagentic/provisioning/harness/goose/`.
- No global `goose configure` required.

## Non-goals

- No MCP tools.
- No provisioning catalog.
- No install/uninstall component actions.
- No bundled llamafile.
