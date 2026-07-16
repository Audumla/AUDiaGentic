# Kilo Code Provider — P1 New Candidate Evidence

<a name="kilo-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `kilo` |
| upstream-id | kilocodeai/kilocode (GitHub) |
| tool-version | probe-required |
| verified-at | 2026-07-16 UTC |
| evidence-kind | upstream documentation review (kilo.ai docs: ai-providers, cli config, custom-models) |

---

## Provider configuration

Kilo Code uses shared CLI/editor JSONC provider configuration. The config file is `kilo.jsonc`. Model IDs follow `provider_id/model_id` format.

### Config shape

Provider configuration mirrors OpenCode's structure with top-level `provider` key:

```jsonc
{
  "provider": {
    "openai": {
      "models": {
        "gpt-5": {
          "options": {
            "reasoningEffort": "high"
          }
        }
      }
    }
  }
}
```

### Custom OpenAI-compatible providers

Kilo Code supports custom providers via the UI or CLI config:

- Provider ID: unique identifier (e.g., `my-provider`)
- Display name: human-readable label
- Provider API: OpenAI Compatible, OpenAI Responses, Anthropic Messages
- Base URL: API endpoint; Kilo auto-fetches models from `/v1/models`
- API key: optional (leave empty if auth is header-based)
- Models: manual entry or auto-fetched list
- Headers: optional custom HTTP headers

### Automatic model detection

When a valid base URL and API key are provided, Kilo queries the provider's `/v1/models` endpoint and presents a searchable model picker. This eliminates manual model ID lookup.

### Full endpoint URL support

Kilo accepts full endpoint URLs (not just base + `/v1`), enabling non-standard gateway integration:

```
https://api.provider.com/v1/chat/completions
https://custom-endpoint.provider.com/api/v2/models/chat
```

---

## Azure GPT-5 special case

Azure GPT-5 deployments reject `max_tokens` (sent by generic OpenAI-compatible providers). Kilo requires the native `azure` provider. If the deployment name differs from the model name, map it with the model `id` field in `kilo.jsonc`.

---

## Config surface (upstream-only facts)

| Field | Value |
|---|---|
| **Config format** | JSONC (comments preserved) |
| **Config file** | `kilo.jsonc` (CLI and editor shared) |
| **Provider block shape** | `{provider: {<id>: {npm, name, options, models}}}` |
| **Model config shape** | Auto-fetched or explicit; `provider_id/model_id` format |
| **Key mechanism** | Env/tool-auth owned; inline key injection not recommended |

---

## Wire/protocol capabilities (expected)

| Capability | Support |
|---|---|
| OpenAI Chat Completions | Yes (default for openai-compatible) |
| OpenAI Responses API | Provider dependent (selectable per provider) |
| Anthropic Messages | Yes (native provider support + compatible custom) |
| Gemini native | Yes (native provider support) |
| Ollama/LM Studio | Yes (local providers) |

---

## Projection mode implications for AG

- **Custom-entries**: Primary path. Write `{provider: {<id>: {...}}}` into project `kilo.jsonc`. BLOCKED until installed schema, project/global precedence, and reload behavior are verified.
- **Discovery**: Kilo supports auto-fetch from `/v1/models`; AG should persist a filtered explicit list for deterministic validation.
- **JSONC preservation**: Must preserve comments in the managed file.
- **Priority**: P1 structured project adapter after shared JSON/JSONC managed-config support lands. Use same parse/merge model as OpenCode but separate descriptor/schema.

---

## Open validation items

| Item | Status |
|---|---|
| Installed schema compatibility with OpenCode-derived fields | probe-required |
| Project vs global config path and precedence | probe-required |
| JSONC comment preservation during managed writes | probe-required |
| Editor/CLI reload behavior after config change | probe-required |
| Wire API selection per provider type | probe-required |
