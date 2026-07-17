# OpenCode Provider — P1 Vendor Verification Evidence (RV350/RV353 Corrected)

<a name="opencode-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `opencode` |
| upstream-id | opencode-ai/opencode (Vercel AI SDK based) |
| tool-version | 1.17.18 (installed); upstream docs revalidated 2026-07-16 |
| verified-at | 2026-07-13 UTC (RV350/RV353 correction), 2026-07-16 UTC (upstream doc revalidation) |
| evidence-kind | installed-tool CLI probe + `opencode models --verbose` catalog enumeration + `opencode providers list` credential surface + upstream doc verification (models.md, config.md, providers.md) |
| **correction-note** | RV350/RV353 corrections: (a) env var key injection NOT supported for native vendors — Anthropic and Google probes confirmed rejection with env vars present; OpenAI env path untested (OAuth available masks rejection proof). (b) Model granularity "all models per vendor" is EXPECTED pattern based on OpenAI catalog behavior, not verified for Anthropic/Google without authenticated access. (c) OpenRouter absence from `providers list` is a probe observation — unsupported requires authoritative capability inventory or negative config test (not yet run). (d) Config filename/container: `providers` key accepted in `.opencode/config.json`; `provider` vs `providers` and winning filename between `.opencode/config.json` and `.opencode/opencode.json` remain unresolved. **2026-07-16 revalidation**: upstream docs confirm `opencode.json`/`opencode.jsonc` with top-level `provider` singular (not `providers` plural); model format is `provider_id/model_id`; variants system exists; recommended models include GPT 5.2, Claude Opus/Sonnet 4.5, Minimax M2.1, Gemini 3 Pro; custom providers support full provider/models/variants config.

---

## Vendor: OpenAI

<a name="opencode-openai"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `opencode providers list` shows "OpenAI oauth"; `opencode models openai` returns 20+ active models with `providerID: "openai"`, API id `@ai-sdk/openai`; model key format `openai/<model-id>` (e.g. `openai/gpt-5.6`) |
| **Sanitized summary** | OpenAI is a native, built-in credential provider using OAuth login flow. Models appear in the runtime catalog when the user has authenticated via `opencode providers login`. Standard env var (`OPENAI_API_KEY`) NOT tested for native path because models are already available via OAuth — rejection not proved. The AI SDK package used is `@ai-sdk/openai` (native, not openai-compatible fallback). Model set granularity: **all models per vendor** — the catalog enumerates every model OpenCode's AI SDK integration knows about; no AG-side model-filter applies. |
| **Support state** | **verified native** (OAuth credential required via login) |
| **Key mechanism** | OAuth login stores credentials in `~\.local\share\opencode\auth.json`; env var path untested (available models mask rejection proof) |

---

## Vendor: Anthropic

<a name="opencode-anthropic"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `opencode providers list` shows "Anthropic oauth"; `opencode models anthropic` returns `Error: Provider not found: anthropic`; setting `ANTHROPIC_API_KEY` env var does NOT enable the provider — same error persists |
| **Sanitized summary** | Anthropic is listed as a supported credential provider (OAuth method). The provider requires user to run `opencode providers login -p anthropic`. Standard env var key injection (`ANTHROPIC_API_KEY`) is confirmed NOT accepted by isolated probe with env var present and provider still unavailable. Model set granularity EXPECTED: **all models per vendor** (same pattern as OpenAI), but cannot verify without credentials. |
| **Support state** | **verified native** (OAuth credential required; env var key injection blocked — confirmed by isolated probe) |
| **Key mechanism** | OAuth login only; stores in `~\.local\share\opencode\auth.json`. No env var path. |

---

## Vendor: Google (Gemini)

<a name="opencode-google"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `opencode providers list` shows "Google api"; `opencode models google` returns `Error: Provider not found: google`; setting `GOOGLE_API_KEY` env var does NOT enable the provider — same error persists |
| **Sanitized summary** | Google is listed as a supported credential provider (API key method, distinct from OAuth). The provider requires configuration via `opencode providers login -p google`. Standard env var key injection (`GOOGLE_API_KEY`) is confirmed NOT accepted by isolated probe with env var present and provider still unavailable. Model set granularity EXPECTED: **all models per vendor**. Cannot verify model list without credentials on this machine. |
| **Support state** | **verified native** (API key credential required via OpenCode login; env var key injection blocked — confirmed by isolated probe) |
| **Key mechanism** | API key stored via `opencode providers login`; stored in `~\.local\share\opencode\auth.json`. No env var path. |

---

## Vendor: OpenRouter

<a name="opencode-openrouter"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `opencode providers list` output contains 6 entries (OpenAI, OpenCode Zen, Anthropic, GitHub Copilot, Google, DeepSeek); OpenRouter is NOT listed among supported credential providers. No negative config test has been run. |
| **Sanitized summary** | OpenRouter is not a native credential provider in OpenCode v1.17.18. It cannot be enabled via `opencode providers login`. The only potential path is adding a custom openai-compatible provider entry to `.opencode/config.json` with an OpenRouter base URL and API key, which would use the `@ai-sdk/openai-compatible` adapter (same as custom `brutus`/`ymir` providers in catalog). This path requires structured config writes and has not been verified. |
| **Support state** | **blocked: native support absent; custom-entries path unverified** — `.opencode/config.json` write gated by MO03 path/container unification; no negative authoritative test confirms unsupported status |
| **Missing evidence** | Whether a custom openai-compatible provider entry with OpenRouter base URL and API key is accepted by the installed OpenCode version. Requires structured config write test, blocked until MO03 resolves. |

---

## Config surface

| Field | Value |
|---|---|
| **Config file** | `.opencode/config.json` (project-local) with top-level `providers` block; `~\.local\share\opencode\auth.json` for OAuth/API credentials. Descriptor-managed MCP/LSP surface is `.opencode/opencode.json` — two different files. |
| **Config shape** | Provider entries: `{name, api, baseURL, apiKey, models:{...}}`. The harness materializer writes to `.opencode/config.json`. |
| **Provider vs providers** | Config uses `providers` (plural) at top level; individual provider blocks keyed by source-id. UNRESOLVED CONTRACT QUESTION: whether installed OpenCode expects `provider` or `providers` for model config and which file wins (`.opencode/config.json` vs `.opencode/opencode.json`). Runtime evidence shows `providers` key is accepted, but the file precedence question remains open. |
| **Catalog refresh** | `opencode models --verbose` reads from cached catalog on models.dev; supports `--refresh` flag to re-fetch. `_fetch_opencode_catalog` adapter wraps this correctly. |

---

## New upstream capabilities (verified 2026-07-16 from docs.opencode.ai)

### Config file and key name

Upstream documentation uses `opencode.json` or `opencode.jsonc` with top-level `provider` **singular** (not `providers`). The installed harness uses `.opencode/config.json` with `providers`. This discrepancy is the MO03 migration gate.

### Model format

Full model ID is `provider_id/model_id`, e.g. `opencode/gpt-5.1-codex` or `lmstudio/google/gemma-3n-e4b`. Set via top-level `model` key.

### Recommended models (upstream list)

- GPT 5.2
- GPT 5.1 Codex
- Claude Opus 4.5
- Claude Sonnet 4.5
- Minimax M2.1
- Gemini 3 Pro

### Variants system

OpenCode supports built-in and custom variants for the same model:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "openai": {
      "models": {
        "gpt-5": {
          "variants": {
            "thinking": {
              "reasoningEffort": "high",
              "textVerbosity": "low"
            },
            "fast": {
              "disabled": true
            }
          }
        }
      }
    }
  }
}
```

Built-in variant defaults per provider:
- **Anthropic**: `high` (default), `max`
- **OpenAI**: `none`, `minimal`, `low`, `medium`, `high`, `xhigh` (varies by model)
- **Google**: `low`, `high`

Cycle variants via keybind `variant_cycle`.

### Global model configuration

Models can be configured globally per provider:

```jsonc
{
  "provider": {
    "openai": {
      "models": {
        "gpt-5": {
          "options": {
            "reasoningEffort": "high",
            "textVerbosity": "low",
            "reasoningSummary": "auto",
            "include": ["reasoning.encrypted_content"]
          }
        }
      }
    },
    "anthropic": {
      "models": {
        "claude-sonnet-4-5-20250929": {
          "options": {
            "thinking": {
              "type": "enabled",
              "budgetTokens": 16000
            }
          }
        }
      }
    }
  }
}
```

### Custom providers via config

Custom providers use the AI SDK provider npm package:

```jsonc
{
  "provider": {
    "audiagentic-local": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "AUDiaGentic Local",
      "options": {
        "baseURL": "http://127.0.0.1:1234/v1"
      },
      "models": {
        "qwen3-coder": {
          "name": "Qwen local"
        }
      }
    }
  },
  "model": "audiagentic-local/qwen3-coder"
}
```

### Model loading priority

1. `--model` / `-m` CLI flag (format: `provider_id/model_id`)
2. `model` key in config file
3. Last used model
4. First model using internal priority

---

## ACP status

| Field | Value |
|---|---|
| **ACP support** | Native |
| **Registry ID** | `opencode` |
| **Launch command** | `opencode acp` |
| **Distribution** | Binary (6 platforms), SHA256 verified |
| **Model override in ACP** | `OPENCODE_CONFIG_CONTENT` env var (inline JSON) |

OpenCode natively implements ACP. No wrapper package needed. The `acp` subcommand starts a JSON-RPC-over-stdio server that can be driven by any ACP host (e.g., OpenHands Agent Canvas).

## Config override at startup

| Field | Value |
|---|---|
| **CLI flag** | No dedicated `--config` flag |
| **Env var: file path** | `OPENCODE_CONFIG` — alternate config file path |
| **Env var: inline JSON** | `OPENCODE_CONFIG_CONTENT` — inline JSON config content, no file I/O needed |
| **Env var: config dir** | `OPENCODE_CONFIG_DIR` — alternate config directory |
| **Env var: TUI config** | `OPENCODE_TUI_CONFIG` — alternate TUI-specific config |

OpenCode provides the strongest config isolation in our provider set. `OPENCODE_CONFIG_CONTENT` allows launching with a completely independent config without any filesystem interaction — multiple concurrent providers with different configs can run simultaneously.

---

## Projection mode implications for AG

- **Native-key-injection (env)**: NOT viable for Anthropic/Google (confirmed blocked by probe). OpenAI env path untested — available via OAuth masks rejection proof. Overall pattern: OpenCode requires its own credential flow (`opencode providers login`). AG cannot inject API keys via ambient environment variables to enable a native provider.
- **Native-key-injection (config)**: Potentially viable if AG writes a provider entry with `apiKey` into `.opencode/config.json`, but the exact key name for built-in vendor auth in the config is unknown and requires structured write verification (gated by MO03).
- **Custom-entries**: Requires writing explicit model entries into `.opencode/config.json`. Also gated by MO03 path/container unification.
- **Practical path for P1 vendors**: User runs `opencode providers login` for each vendor; AG reads the resulting catalog via `_fetch_opencode_catalog` to validate availability. This is a "user-managed credential, AG-monitored availability" pattern, not key injection.
