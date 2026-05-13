# Stage 0 acceptance checks

## Local LLM endpoint

Port is auto-selected at launch. Check the footer or runner output for the active URL.

```bash
curl http://127.0.0.1:<port>/v1/models
```

## Pi installs repo-locally

```text
audiagentic install
```

Expected files:

```text
.audiagentic/harness/node/node_modules/.bin/pi
.audiagentic/harness/agent/models.json
.audiagentic/harness/agent/mcp.json
```

## Pi launches local model

```text
audiagentic
```

Prompt:

```text
Respond with exactly: audiagentic-pi-local-ok
```

## MCP smoke

MCP is opt-in.

```text
audiagentic --smoke --enable-mcp
```

Prompt Pi:

```text
Use the MCP adapter to call audiagentic_smoke_status and report the JSON result.
```

Expected result has `ok: true`, `readonly: true`, `smoke_only: true`, and repo root.
