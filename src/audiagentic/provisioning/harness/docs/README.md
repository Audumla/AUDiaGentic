# Pi harness for AUDiaGentic provisioning

Stage 0 harness for Pi against the repo-local OpenAI-compatible model endpoint.
AUDiaGentic MCP tools are opt-in.

## Quick start

```text
audiagentic install
audiagentic
```

Smoke:

```text
audiagentic --smoke
```

MCP opt-in:

```text
audiagentic --enable-mcp
audiagentic --smoke --enable-mcp
```

## Defaults

```text
Model:        qwen3.5-9b-flash  (config/config.yaml)
Model file:   resolved from models.json profile (model_file field)
Runtime:      .audiagentic/harness/
Port:         auto-selected (0 = free port chosen at launch)
MCP:          disabled unless --enable-mcp or AUDIAGENTIC_PI_ENABLE_MCP=1
Model profiles: src/audiagentic/provisioning/rig/embedded/models.json
```

Rig type is determined by the model profile: profiles with `model_file` launch an
embedded llama-server; profiles without use the external endpoint at
`AUDIAGENTIC_PI_BASE_URL`.

Override with:

```bash
AUDIAGENTIC_PI_MODEL=qwen3.5-9b-flash
AUDIAGENTIC_PI_BASE_URL=http://127.0.0.1:<port>/v1
AUDIAGENTIC_PI_API_KEY=dummy
AUDIAGENTIC_PI_ENABLE_MCP=1
AUDIAGENTIC_PI_MODEL_PROFILE=qwen3.5-9b-flash
```

Rig model profiles own llama-server launch settings: model file, context,
GPU layers, sampler defaults, chat template kwargs, and Pi metadata
(`contextWindow`, `maxTokens`, `reasoning`, `compat`).

## Stage 0 scope

- Pi CLI only
- local OpenAI-compatible model endpoint only
- Pi MCP adapter installed repo-locally but disabled by default
- opt-in read-only MCP smoke tool: `audiagentic_smoke_status`
- no install/apply/uninstall/file mutation tools
