# Provider Model Endpoint Capabilities

Status: reference draft
Last validated: 2026-07-09

This document records how AUDiaGentic should reason about local/custom model
configuration across provider adapters. It is intentionally provider-owned:
agent profiles choose a provider/model at dispatch time, while providers own
the config formats, auth conventions, model catalogs, and reload behavior that
make a model available.

## Design Position

Model endpoint propagation belongs in the providers component.

- `agents` should continue to bind jobs to `provider_id` and `model_id`.
- `providers` should own desired local/custom model endpoint state and project
  that state into each compatible provider config.
- Provider adapters should declare how model endpoints are read, written,
  removed, refreshed, and documented.
- Recipes should call provider-owned sync services. They must not hand-write
  provider config files directly.

The closest existing pattern is managed MCP sync:

- Provider descriptor declares format-specific reader/writer/remover.
- A provider service builds desired entries.
- `FragmentStore` + `reconcile_fragments` handles ownership, rename/update, and
  preservation of unmanaged user entries.
- A small runtime registry tracks stable managed ids.

Model endpoints need the same shape, not ad hoc recipe code.

## Proposed Managed Model Shape

Project-level desired state should support multiple local/custom models:

```yaml
contract-version: v1
model-endpoints:
  qwen36-local:
    display-name: Qwen3.6 local
    protocol: openai-compatible
    base-url: http://127.0.0.1:1234/v1
    api-key-ref: env:AUDIAGENTIC_LOCAL_API_KEY
    model-id: qwen3.6-35b-a3b
    context-window: 262144
    max-output-tokens: 4096
    capabilities:
      tool-use: true
      reasoning: false
    provider-overrides:
      pi:
        api: openai-completions
        compat:
          supportsDeveloperRole: false
          supportsReasoningEffort: false
      opencode:
        provider-id: audiagentic
      openhands:
        model-prefix: openai/
```

Stable managed id rule:

- Use `model-endpoints/<endpoint-id>` as the ownership id.
- Provider-visible names may differ per adapter, but ownership id stays stable.
- Updating base URL, context window, token cap, or provider-specific options
  replaces only the managed entry for that id.
- Removing an endpoint removes only entries owned by that id.
- Unmanaged user-defined model/provider entries are preserved.

## Provider Capability Matrix

| Provider | Custom/local endpoint | Multiple models | Config surface | AUDiaGentic current state | Required model sync adapter |
|---|---:|---:|---|---|---|
| `pi` | Yes | Yes | Pi `models.json` providers map | Harness already materializes one primary plus fallback local model | High priority |
| `opencode` | Yes | Yes | `.opencode/opencode.json` provider/model config | Provider adapter manages same file for MCP/LSP; harness writer currently uses `.opencode/config.json`, needs reconciliation | High priority |
| `local-openai` | Yes | Endpoint catalog-derived | AUDiaGentic provider config only | API bridge exists; catalog fetch currently emits invalid schema values | High priority |
| `openhands` | Yes | UI/env/custom model | `.openhands/settings.json` and/or runtime env; MCP uses `.openhands/config.toml` | MCP adapter exists; model config adapter missing | High priority |
| `goose` | Yes | Yes | Goose custom provider config files | MCP adapter exists; model config adapter missing | High priority |
| `codex` | Yes | Provider selectable | `~/.codex/config.toml`, not project provider keys | TOML MCP/LSP writer exists; model provider writer missing | High priority, user-scope caution |
| `qwen` | Yes | Yes | `settings.json` `modelProviders` | CLI model flag exists; settings writer missing | High priority |
| `continue` | Yes | Yes | `config.yaml` `models` entries | MCP JSON writer exists; model YAML writer missing | Medium priority |
| `cline` | Yes | UI/provider profile | VS Code extension settings/profile | No model config writer | Medium priority, storage investigation needed |
| `roo` | Yes | Profiles/providers | VS Code extension settings/profile | MCP writer exists; `access-mode: env` is misleading | Medium priority, storage investigation needed |
| `aider` | Yes | Invocation/env driven | Env vars, CLI args, `.aider.conf.yml` | Execution stub; no config writer | Medium priority |
| `plandex` | Yes | Yes | Custom models/providers/model packs | Execution stub; no config writer | Medium priority |
| `gemini` | Native Google primarily | CLI model flag | Gemini CLI settings/flags | CLI `-m` support exists; custom OpenAI-compatible endpoint not established in official CLI docs | Low/blocked |
| `claude` | Native Anthropic primarily | CLI model flag | Claude CLI settings/flags | Live catalog and `--model` supported; no custom endpoint path validated | Low/blocked |
| `copilot` | Account-derived | Account/model picker | GitHub Copilot account | CLI model path weak; no custom endpoint | Not target |
| `antigravity` | Unknown | Unknown | AGENTS-style surface | No execution/model adapter | Research-only |

## Provider Notes

### Pi

Pi is a custom/local model target. Its docs describe custom providers with
provider-level and model-level compatibility settings, including
`openai-completions` for OpenAI-compatible servers and `compat` overrides for
local servers such as Ollama, vLLM, and SGLang.

AUDiaGentic already has a Pi model shape in
`src/audiagentic/runtime/harness/pi/templates/home/agent/models.json`:

```json
{
  "providers": {
    "audiagentic": {
      "baseUrl": "__AUDIAGENTIC_AG_BASE_URL__",
      "api": "openai-completions",
      "apiKey": "__AUDIAGENTIC_AG_API_KEY__",
      "models": [
        {
          "id": "__AUDIAGENTIC_AG_MODEL__",
          "name": "AUDiaGentic local planner",
          "contextWindow": 262144,
          "maxTokens": 4096
        }
      ]
    }
  }
}
```

Sync implication: Pi should get a provider-model adapter that reconciles
`providers.<provider-id>.models[]` by model id and preserves unmanaged models.

Sources:

- https://pi.dev/docs/latest/custom-provider
- https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md

### OpenCode

OpenCode supports provider/model configuration in `opencode.json`, including
custom providers and default model selection. Its model ids are
`provider_id/model_id`; for custom providers, `provider_id` is the key under
`provider`, and `model_id` is the key under that provider's `models`.

Expected managed shape:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "audiagentic": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "AUDiaGentic local",
      "options": {
        "baseURL": "http://127.0.0.1:1234/v1"
      },
      "models": {
        "qwen36-local": {
          "name": "Qwen3.6 local",
          "contextWindow": 262144,
          "maxTokens": 4096
        }
      }
    }
  },
  "model": "audiagentic/qwen36-local"
}
```

Repo gap: current provider descriptor and MCP/LSP adapters target
`.opencode/opencode.json`, while the runtime harness writer emits
`.opencode/config.json` and uses top-level `providers`. Validate against the
installed OpenCode version before implementing sync.

Sources:

- https://opencode.ai/docs/config/
- https://opencode.ai/docs/models/
- https://opencode.ai/docs/providers/

### Local OpenAI Bridge

This provider is AUDiaGentic's direct OpenAI-compatible HTTP bridge. It already
supports `api-base-url`, API key variants, `default-model`, streaming, and
OpenAI chat completions.

Current issue: `local_openai/catalog.py` returns `status: "available"` and
`context-window: None`, but `provider-model-catalog.schema.json` requires
`status` to be `active|deprecated|experimental` and `context-window` to be a
positive integer. Catalog refresh for this provider cannot persist valid output
until that is fixed.

Sync implication: direct bridge should read shared `model-endpoints` and expose
selected endpoint(s) as provider config aliases/catalog entries.

### OpenHands

OpenHands supports local LLMs and OpenAI-compatible endpoints through LiteLLM.
Docs describe Advanced LLM settings with `Custom Model`, `Base URL`, and
`API Key`; local OpenAI-compatible model strings use the `openai/<model-id>`
convention. The local LLM guide also mentions `LLM_BASE_URL`, `LLM_MODEL`, and
`LLM_API_KEY` for CLI automation.

Sync implication: OpenHands needs a model adapter separate from its existing
MCP TOML adapter. For CLI/harness flows, env projection may be the safest first
target. For persistent UI config, inspect `.openhands/settings.json` format.

Sources:

- https://docs.openhands.dev/openhands/usage/llms/openai-llms
- https://docs.openhands.dev/openhands/usage/llms/local-llms

### Goose

Goose supports custom providers in OpenAI-compatible, Anthropic-compatible, and
Ollama-compatible formats. Docs state each custom provider maps to a JSON config
file, with provider type, display name, API URL, auth, custom headers, and
available model names.

Sync implication: Goose is a strong model sync target. Adapter should reconcile
custom provider JSON entries and preserve unmanaged providers/models.

Source:

- https://goose-docs.ai/docs/getting-started/providers/

### Codex

Codex supports custom model providers in `config.toml`. Providers define base
URL, wire API, auth env key, and optional headers. Config docs also state that
provider keys such as `model_provider` and `model_providers` are ignored in
project-local `.codex/config.toml`; they belong in user-level config.

Expected managed shape:

```toml
model = "qwen36-local"
model_provider = "audiagentic"

[model_providers.audiagentic]
name = "AUDiaGentic local"
base_url = "http://127.0.0.1:1234/v1"
env_key = "AUDIAGENTIC_LOCAL_API_KEY"
```

Sync implication: Codex model sync touches user-level config, not project-local
provider keys. That needs explicit user consent and clear status output.

Sources:

- https://developers.openai.com/codex/config-basic
- https://developers.openai.com/codex/config-advanced
- https://developers.openai.com/codex/config-reference

### Qwen Code

Qwen Code supports multiple providers through `modelProviders` in
`settings.json`. Models can define `id`, `name`, `envKey`, `baseUrl`,
`generationConfig`, `contextWindowSize`, and sampling params.

Sync implication: Qwen should receive one provider entry per endpoint family or
one shared `audiagentic` provider with multiple model entries, depending on how
its `/model` command displays grouped providers.

Source:

- https://github.com/QwenLM/qwen-code/blob/main/docs/users/configuration/model-providers.md

### Continue

Continue `config.yaml` defines `models` entries. Each model has `name`,
`provider`, `model`, optional `apiBase`, roles, and capabilities. Continue docs
also describe OpenAI configuration and disabling the Responses API for GPT-5/o
series when needed.

Expected managed shape:

```yaml
models:
  - name: Qwen3.6 local
    provider: openai
    model: qwen3.6-35b-a3b
    apiBase: http://127.0.0.1:1234/v1
    roles: [chat, edit, apply]
    capabilities: [tool_use]
```

Sync implication: Continue needs YAML config support. Existing repo MCP support
targets `.continue/config.json`, so model sync should decide whether to support
modern YAML first, legacy JSON second, or both.

Sources:

- https://docs.continue.dev/reference
- https://docs.continue.dev/customize/model-providers/top-level/openai
- https://continue-docs.mintlify.app/customize/models

### Cline

Cline supports OpenAI-compatible providers with Base URL, API Key, and Model ID,
including local models through Ollama and LM Studio.

Sync implication: capability is real, but persistent storage format needs
inspection. Until we validate the extension's settings/profile file, this should
be reported as supported-manual rather than auto-managed.

Source:

- https://docs.cline.bot/provider-config/openai-compatible

### Roo Code

Roo Code supports OpenAI-compatible provider setup through extension settings
according to integration docs: provider type, base URL, API key, and model id.

Sync implication: capability is real, but current AUDiaGentic descriptor uses
`access_mode: env`, which makes health require `auth-ref`; that does not model
Roo's extension-managed provider profile well. Add a model config adapter only
after storage format is validated.

Sources:

- https://docs.aimlapi.com/integrations/roo-code
- https://docs.portkey.ai/docs/virtual_key_old/integrations/libraries/roo-code

### Aider

Aider supports any OpenAI-compatible API endpoint via environment variables such
as `OPENAI_API_BASE` and `OPENAI_API_KEY`, plus model selection through CLI or
config.

Sync implication: best first support is launch-time env projection. Persistent
multi-model support may require managed `.aider.conf.yml` entries or separate
AUDiaGentic profiles.

Sources:

- https://aider.chat/docs/llms/openai-compat.html
- https://aider.chat/docs/llms.html

### Plandex

Plandex supports custom providers and custom models. Its docs state all custom
providers must be OpenAI-compatible, and provider/model ids must be unique.

Sync implication: Plandex is compatible, but the repo adapter is still a stub.
Implement after execution/config storage path is wired.

Source:

- https://docs.plandex.ai/models/custom-models/

### Gemini

Gemini CLI in this repo accepts `default-model` through `-m`, but current
official Gemini CLI model endpoint customization is not validated here as a
general OpenAI-compatible local endpoint target. Google Gemini itself exposes
OpenAI-compatible APIs, but that is not the same as proving Gemini CLI can be
managed as a generic local endpoint consumer.

Source:

- https://ai.google.dev/gemini-api/docs/openai

### Claude

Claude provider supports model selection and live catalog fetch in AUDiaGentic,
but no custom local/OpenAI-compatible endpoint path is validated for Claude Code.

### Copilot

Copilot models are account/service-derived. Do not include it in local endpoint
propagation unless GitHub exposes a supported custom endpoint configuration.

### Antigravity

No reliable custom endpoint capability has been validated. Treat as research.

## Implementation Requirements

Add provider descriptor metadata:

```yaml
model_config:
  config_path: ".opencode/opencode.json"
  reader: "..."
  writer: "..."
  remover: "..."
  format: "opencode-json"
  refresh_mode: "file-watch"
  supports:
    openai-compatible: true
    multiple-local-models: true
    provider-auth-trigger: true
```

Add provider service functions mirroring MCP:

- `sync_managed_provider_models(provider_id, project_root, desired_entries)`
- `sync_managed_provider_models_subset(..., managed_ids={...})`
- `list_provider_models_config(provider_id, project_root)`
- `reload_provider_models(provider_id, project_root)`

Use:

- `FragmentStore` and `reconcile_fragments` for structured named entries.
- Provider-owned reader/writer/remover per config format.
- A runtime ownership registry such as
  `.audiagentic/runtime/providers/managed-model-endpoints.json`.
- Provider status fields for `model-config-supported`, `managed-model-count`,
  `model-config-path`, `model-config-refresh-mode`, and conflicts.

Do not:

- Write provider model config directly from recipes.
- Use `apply_managed_block` for JSON/TOML/YAML model entries.
- Overwrite unmanaged provider config.
- Treat account-derived model catalogs as a local endpoint allowlist.
- Conflate AUDiaGentic providers with upstream model vendors. For example,
  `opencode` is an AUDiaGentic provider; `openai`, `openrouter`, and
  `audiagentic-local` are model endpoint providers inside OpenCode.

## First Implementation Order

1. Fix `local-openai` catalog validation.
2. Add shared model endpoint config and tests for multiple local models.
3. Add OpenCode model config adapter after resolving `opencode.json` vs
   `config.json` and `provider` vs `providers`.
4. Add Pi model config adapter by reconciling `models.json` providers/models.
5. Add OpenHands env/settings projection.
6. Add Goose, Codex, and Qwen writers.
7. Add Continue YAML writer.
8. Add Cline/Roo only after extension config storage is validated.

