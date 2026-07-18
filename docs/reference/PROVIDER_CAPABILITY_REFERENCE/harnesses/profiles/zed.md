# Zed Provider — P2 New Candidate Evidence

<a name="zed-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `zed` |
| upstream-id | zed-industries/zed (GitHub) |
| tool-version | probe-required |
| verified-at | 2026-07-16 UTC |
| evidence-kind | upstream documentation review (nightly docs: llm-providers.md, use-api-access.md, use-a-local-model.md) |

---

## Provider configuration

Zed uses a documented, public settings surface for custom OpenAI-compatible and Anthropic-compatible models. Credentials are stored in the system keychain or via environment variables — never in `settings.json`.

### First-class API providers

| Provider | Env var | Notes |
|---|---|---|
| Anthropic | `ANTHROPIC_API_KEY` | Custom models with `tool_override`, `mode.thinking`, thinking budget |
| OpenAI | `OPENAI_API_KEY` | Custom models with `reasoning_effort`, `max_completion_tokens` |
| Google AI | `GEMINI_API_KEY` / `GOOGLE_AI_API_KEY` | Custom models with `mode.thinking` |
| Mistral | `MISTRAL_API_KEY` | Custom models with `supports_tools`, `supports_images` |
| DeepSeek | `DEEPSEEK_API_KEY` | Custom models with per-model endpoints |
| xAI (Grok) | `XAI_API_KEY` | Custom models with vision support |
| OpenCode API | `OPENCODE_API_KEY` | Free/Zen/Go model filtering; custom models with protocol selection |

### Custom OpenAI-compatible providers

```json
{
  "language_models": {
    "openai_compatible": {
      "my-provider": {
        "api_url": "https://example.com/v1",
        "available_models": [
          {
            "name": "my-model",
            "display_name": "My Model",
            "max_tokens": 128000
          }
        ]
      }
    }
  }
}
```

### Custom Anthropic-compatible providers

```json
{
  "language_models": {
    "anthropic_compatible": {
      "Some Provider": {
        "api_url": "https://api.someprovider.com",
        "custom_headers": {
          "X-Some-Header": "some-value"
        },
        "available_models": [
          {
            "name": "some-model",
            "display_name": "Some Model",
            "max_tokens": 200000,
            "max_output_tokens": 32000,
            "capabilities": {
              "tools": true,
              "images": false,
              "prompt_caching": false
            }
          }
        ]
      }
    }
  }
}
```

### Local providers

Zed has first-class local provider support for:

| Provider | Autodiscovery | Key env var | Config key |
|---|---|---|---|
| llama.cpp | Yes (via `/models/sse`) | `LLAMACPP_API_KEY` | `language_models.llama.cpp` |
| Ollama | Yes | `OLLAMA_API_KEY` | `language_models.ollama` |
| LM Studio | Yes | `LMSTUDIO_API_KEY` | `language_models.lmstudio` |
| Local OpenAI-compatible | Manual | Generated from provider ID | `language_models.openai_compatible` |

### Wire API selection per model

Zed can select Chat Completions or Responses **per model** for OpenAI-compatible providers:

- Default: `chat_completions = true` (Chat Completions path)
- Set `chat_completions = false` to force the Responses API endpoint
- Reasoning models may require Responses API for reasoning state: set `chat_completions = false`

### Custom headers

All supported HTTP-based providers accept per-provider custom headers:

```json
{
  "language_models": {
    "openai": {
      "custom_headers": {
        "Fancy-Auth": "Bearer <your-fancy-key>"
      }
    }
  }
}
```

Supported on: Amazon Bedrock, Anthropic, DeepSeek, Google AI, LM Studio, Mistral, Ollama, OpenAI, OpenAI-compatible, OpenCode, OpenRouter, Vercel AI Gateway, and xAI.

### Reasoning effort

For OpenAI-style reasoning models, set `reasoning_effort` to enable thinking:

```json
{
  "language_models": {
    "openai_compatible": {
      "my-provider": {
        "available_models": [
          {
            "name": "gpt-5",
            "max_tokens": 272000,
            "reasoning_effort": "high",
            "capabilities": {
              "chat_completions": false,
              "interleaved_reasoning": false,
              "max_tokens_parameter": false
            }
          }
        ]
      }
    }
  }
}
```

Valid values: `"none"`, `"minimal"`, `"low"`, `"medium"`, `"high"`, `"xhigh"`, `"max"`.

### Model capabilities model

OpenAI-compatible default capabilities:
- `tools`: `true`
- `images`: `false`
- `parallel_tool_calls`: `false`
- `prompt_cache_key`: `false`
- `chat_completions`: `true`
- `interleaved_reasoning`: `false`
- `max_tokens_parameter`: `false`

Anthropic-compatible default capabilities:
- `tools`: `true`
- `images`: `false`
- `prompt_caching`: `false`

---

## Config surface (upstream-only facts)

| Field | Value |
|---|---|
| **Config format** | JSON (`settings.json`) |
| **Config location** | Editor-global; project-scope needs verification |
| **Provider block shape** | `language_models.<provider_id>.<provider_name>` with `available_models[]` |
| **Model config shape** | `{name, display_name, max_tokens, max_output_tokens, reasoning_effort, capabilities}` |
| **Key mechanism** | System keychain (via UI) or env var per provider. Never in `settings.json`. |
| **Reload behavior** | Probe-required — settings reload vs restart-session |

---

## Wire/protocol capabilities (verified)

| Capability | Support |
|---|---|
| OpenAI Chat Completions | Yes (default for openai_compatible) |
| OpenAI Responses API | Yes, per-model by setting `chat_completions = false` |
| Anthropic Messages | Yes, via anthropic_compatible with full capability model |
| Gemini native | Yes (first-class Google AI provider) |
| Ollama/LM Studio/llama.cpp | Yes (first-class local providers with autodiscovery) |
| Custom headers | Yes (all HTTP-based providers) |

---

## ACP status

| Field | Value |
|---|---|
| **ACP support** | None (not listed in registry) |
| **Registry ID** | N/A — not in ACP registry v1.0.0 |

Zed is not currently listed in the ACP registry v1.0.0. No ACP adapter package exists for this provider.

## Config override at startup

| Field | Value |
|---|---|
| **CLI flag** | No documented `--config` flag |
| **Env var** | No documented env var for config override |

Zed does not support startup config override.

---

## Projection mode implications for AG

- **Custom-entries**: Primary path. Write `language_models.openai_compatible.<provider>` or `anthropic_compatible.<provider>` entries into user-global `settings.json`. BLOCKED on project-scope verification, settings merge behavior, reload behavior, and default model pointer.
- **Credentials**: Never write keys to `settings.json`; use env vars. Generated env var name follows pattern `<PROVIDER_NAME>_API_KEY` (e.g., `MY_PROVIDER_API_KEY`).
- **Autodiscovery**: Local providers support autodiscovery; AG should persist explicit filtered model lists for deterministic validation.
- **Priority**: P2 new `auto-user-consent` candidate. Requires user-global write consent gate.

---

## Open validation items

| Item | Status |
|---|---|
| Settings scope and merge behavior (project vs global) | probe-required |
| Generated env-var naming for custom providers | documented as `<PROVIDER_NAME>_API_KEY` |
| Settings reload behavior (hot-reload vs restart-session) | probe-required |
| Default model pointer management | probe-required |
| Project-scope config availability | probe-required |
