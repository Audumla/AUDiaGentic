# Stage 0 acceptance checks

## Local LLM endpoint

```bash
curl http://127.0.0.1:42001/v1/models
```

## Pi installs repo-locally

```text
python -m audiagentic.provisioning.harness.pi.install
```

Expected files:

```text
.audiagentic-dev/pi/node/node_modules/.bin/pi
.audiagentic-dev/pi/home/.pi/agent/models.json
.audiagentic-dev/pi/home/.pi/agent/mcp.json
```

## Pi launches local model

```text
python -m audiagentic.provisioning.harness.pi.runner
```

Prompt:

```text
Respond with exactly: audiagentic-pi-local-ok
```

## MCP smoke

MCP is opt-in.

```text
python -m audiagentic.provisioning.harness.pi.runner --smoke --enable-mcp
```

Prompt Pi:

```text
Use the MCP adapter to call audiagentic_smoke_status and report the JSON result.
```

Expected result has `ok: true`, `readonly: true`, `smoke_only: true`, and repo root.
