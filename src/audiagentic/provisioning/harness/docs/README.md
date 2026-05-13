# Pi harness for AUDiaGentic provisioning

Stage 0 harness for Pi against the repo-local OpenAI-compatible model endpoint.
AUDiaGentic MCP tools are opt-in.

## Quick start

```text
python -m audiagentic.provisioning.harness.pi.install
python -m audiagentic.provisioning.harness.pi.runner
```

Smoke:

```text
python -m audiagentic.provisioning.harness.pi.runner --smoke
```

MCP opt-in:

```text
python -m audiagentic.provisioning.harness.pi.runner --enable-mcp
python -m audiagentic.provisioning.harness.pi.runner --smoke --enable-mcp
```

## Defaults

```text
Endpoint: http://127.0.0.1:42001/v1
Model: Qwen_Qwen3.5-2B-Q4_K_S.gguf
Fallback: Qwen_Qwen3.5-2B-Q4_K_S.gguf
Runtime: .audiagentic-dev/pi/
MCP: disabled unless --enable-mcp or AUDIAGENTIC_PI_ENABLE_MCP=1
Model profile: src/audiagentic/provisioning/rig/embedded/models.json
```

Override with:

```bash
AUDIAGENTIC_PI_MODEL=Qwen_Qwen3.5-2B-Q4_K_S.gguf
AUDIAGENTIC_PI_BASE_URL=http://127.0.0.1:42001/v1
AUDIAGENTIC_PI_API_KEY=dummy
AUDIAGENTIC_PI_ENABLE_MCP=1
AUDIAGENTIC_PI_MODEL_PROFILE=qwen3.5-2b-q4_k_s
```

Rig model profiles own llama-server launch settings such as model file, context,
GPU layers, sampler defaults, and chat template kwargs. The Pi harness uses the
same profile for model metadata.

## Stage 0 scope

- Pi CLI only
- local OpenAI-compatible model endpoint only
- Pi MCP adapter installed repo-locally but disabled by default
- opt-in read-only MCP smoke tool: `audiagentic_smoke_status`
- no install/apply/uninstall/file mutation tools
