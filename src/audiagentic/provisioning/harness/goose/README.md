# AUDiaGentic Stage 0: Goose + local LLM harness

Repo-local Goose binary talking to the existing llama-swap endpoint.

## Quick start

```text
python -m audiagentic.provisioning.harness.goose.runner
```

Expected smoke output:

```text
audiagentic-goose-local-ok
```

## LLM endpoint

Shared config: `src/audiagentic/provisioning/llm/config.yaml`

Default endpoint: `http://10.10.200.52:13305/v1` (llama-swap)
Default model: `qwen3.5-2b`

Override:

```bash
export OPENAI_HOST="http://10.10.200.52:13305/v1"
export GOOSE_MODEL="gemma4-E4B"
```

## Runtime paths

- Binary: `.audiagentic/provisioning/goose/bin/`
- Sessions/state: `.audiagentic/runtime/goose/`
- Logs: `.audiagentic/provisioning/logs/goose/`

Neither is tracked by git.

## Stage 0 scope

Prove Goose runs from this repo and can call the local model. No MCP tools,
no provisioning catalog, no install logic. Those come after this works.
