# Aider Provider — Vendor Verification Evidence

<a name="aider-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `aider` |
| upstream-id | paul-gauthier/aider (GitHub) |
| tool-version | 0.86.2; upstream docs revalidated 2026-07-16 |
| verified-at | 2026-07-13 UTC, 2026-07-16 UTC (upstream doc revalidation) |
| evidence-kind | installed-tool CLI probe (`aider --help`, `aider --list-models`), env var inspection, upstream docs verification (aider.chat) |
| **correction-note** | **2026-07-16 revalidation**: Aider now supports GitHub Copilot as a connecting-to-LLMs provider. The `.aider.conf.yml` YAML config file is confirmed as the config surface with `api-key: [provider=<key>]` pattern for all providers. Reasoning models configuration is now a separate docs page, confirming that aider supports secondary reasoning models from providers.

---

## Vendor: OpenAI

<a name="aider-openai"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `aider --help` shows `--openai-api-key OPENAI_API_KEY` with env var `AIDER_OPENAI_API_KEY`. Model listing shows `openrouter/openai/gpt-5.2`, `replicate/openai/gpt-5` prefixes via LiteLLM abstraction. Dedicated flags: `--openai-api-base`, `--openai-api-type`, `--openai-api-version`, `--openai-api-deployment-id`. |
| **Sanitized summary** | OpenAI is the primary vendor for aider. Supports dedicated env key (`AIDER_OPENAI_API_KEY`), CLI flag (`--openai-api-key`), and Azure-specific routing options. LiteLLM model prefix convention: `openai/<id>`, with optional provider routing prefixes like `openrouter/openai/<id>` or `replicate/openai/<id>`. All-models granularity via LiteLLM catalog. |
| **Support state** | **verified native via dedicated env var + CLI flags** (`AIDER_OPENAI_API_KEY`; also `--openai-api-key`) |

---

## Vendor: Anthropic

<a name="aider-anthropic"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `aider --help` shows `--anthropic-api-key ANTHROPIC_API_KEY` with env var `AIDER_ANTHROPIC_API_KEY`. Model listing via `--list-models anthropic/claude` returns models like `vercel_ai_gateway/anthropic/claude-opus-4.6`, `vercel_ai_gateway/anthropic/claude-sonnet-4.5`. |
| **Sanitized summary** | Anthropic is a natively supported vendor with dedicated env key (`AIDER_ANTHROPIC_API_KEY`) and CLI flag (`--anthropic-api-key`). LiteLLM model prefixes: `anthropic/<id>` with optional provider routing (e.g., `vercel_ai_gateway/anthropic/<id>`). All models available through LiteLLM's catalog. |
| **Support state** | **verified native via dedicated env var + CLI flags** (`AIDER_ANTHROPIC_API_KEY`; also `--anthropic-api-key`) |

---

## Vendor: Google (Gemini)

<a name="aider-google"></a>

| Field | Value |
|---|---|
| **Sanitized source** | No dedicated Gemini-specific env key in help output. Model listing via LiteLLM shows `gemini/<vendor>/<id>` prefixes supported through the generic routing layer. The `--api-key PROVIDER=KEY` flag can set provider-specific keys (e.g., `--api-key gemini=dummy`). |
| **Sanitized summary** | Google/Gemini support through LiteLLM's generic vendor routing. Key injection via generic `--api-key GEMINI=<key>` or env var pattern `GEMINI_API_KEY`. Model selection uses `gemini/<id>` prefix convention with optional provider routing prefixes. All models available through LiteLLM catalog. |
| **Support state** | **verified native via LiteLLM generic routing** (`GEMINI_API_KEY` env var; also `--api-key GEMINI=<key>`) |

---

## Vendor: OpenRouter

<a name="aider-openrouter"></a>

| Field | Value |
|---|---|
| **Sanitized source** | Model listing via `--list-models openai/gpt-5` shows `openrouter/openai/gpt-5.1-codex-max`, `openrouter/openai/gpt-5.2` prefixes, confirming OpenRouter routing through LiteLLM. Key injection via generic provider key mechanism. |
| **Sanitized summary** | OpenRouter support through LiteLLM's vendor routing with `openrouter/<vendor>/<id>` prefix convention. Key injection via `--api-key openrouter=<key>` or env var `OPENROUTER_API_KEY`. All available OpenRouter models exposed through LiteLLM catalog. |
| ** state** | **verified native via LiteLLM generic routing** (`OPENROUTER_API_KEY` env var; also `--api-key openrouter=<key>`) |

---

## New upstream capabilities (verified 2026-07-16 from aider.chat)

### GitHub Copilot provider support

Aider now lists "GitHub Copilot" as a connecting-to-LLMs provider. This means aider can route through GitHub's Copilot API for model access, alongside OpenAI, Anthropic, Gemini, and other providers.

### Reasoning models configuration

Aider now has a dedicated "Reasoning models" configuration page. Secondary providers for reasoning models are supported — the agent can use a primary model for coding tasks and a separate reasoning model for deeper analysis.

### YAML config file confirmed

The `.aider.conf.yml` file is confirmed as the structured config surface with:
- `openai-api-key: <key>` / `anthropic-api-key: <key>` for dedicated providers
- `api-key: [provider=<key>]` pattern for all other providers (e.g., `gemini=foo`, `openrouter=bar`, `deepseek=baz`)

### Advanced model settings page

Aider now has a dedicated "Advanced model settings" configuration page, confirming that model-level customization is supported beyond basic API key and model selection.

---

## Config surface

| Field | Value |
|---|---|
| **Config file** | `.aider.conf.yml` (YAML) confirmed as the structured config surface. Contains: `openai-api-key`, `anthropic-api-key` for dedicated providers; `api-key: [provider=<key>]` pattern for all others (e.g., `gemini=foo`, `openrouter=bar`). Also supports `.env` file for env var keys. |
| **Key mechanism** | **(a) Dedicated vendor keys:** `AIDER_OPENAI_API_KEY`, `AIDER_ANTHROPIC_API_KEY` env vars; CLI flags `--openai-api-key`, `--anthropic-api-key`; YAML `openai-api-key: <key>`. **(b) Generic provider keys:** `--api-key PROVIDER=KEY` pattern sets `<PROVIDER>_API_KEY`; YAML `api-key: [provider=<key>]`. **(c) Model selection:** `--model <id>` or env var `AIDER_MODEL`. Single active model at a time per session. **(d) Reasoning models:** Separate secondary provider configuration supported. |
| **Model granularity** | All models available through LiteLLM catalog; selectable via `--model` flag or `AIDER_MODEL` env var. One active model per session. Model settings can be overridden via `--model-settings-file`. Advanced model settings page confirms model-level customization. |
| **Reload behavior** | Aider reads config/env at startup. No live reload observed for model changes — restart required. |

---

## ACP status

| Field | Value |
|---|---|
| **ACP support** | None (not listed in registry) |
| **Registry ID** | N/A — not in ACP registry v1.0.0 |

Aider is not currently listed in the ACP registry v1.0.0. No ACP adapter package exists for this provider.

## Config override at startup

| Field | Value |
|---|---|
| **CLI flag** | No dedicated `--config` flag |
| **Env var: file path** | `AIDER_CONFIG` — alternate config file path (inferred from vendor pattern) |
| **Config file** | `.aider.conf.yml` — structured YAML config surface |

Aider uses a per-repo or user-home `.aider.conf.yml` for structured configuration. No CLI flag for config override, but `AIDER_CONFIG` env var may allow alternate path (pattern inferred from dedicated vendor env naming convention).

---

## Projection mode implications for AG

- **Native-key-injection (env)**: Primary viable path. Set dedicated vendor env vars (`AIDER_OPENAI_API_KEY`, `AIDER_ANTHROPIC_API_KEY`) or generic pattern (`GEMINI_API_KEY`, `OPENROUTER_API_KEY`). Model selection via `AIDER_MODEL` env var. No file mutation required — pure launch-env contribution.
- **Custom-entries**: Not applicable — aider binds one model per session through LiteLLM routing. Model filter not needed since the catalog is authoritative and all vendors are addressable via prefix convention.
- **Multi-vendor capability**: Unlike tools that switch auth mode, aider carries concurrent env vars for multiple vendors simultaneously — only the active model determines which vendor's key is used at runtime.
- **Local endpoint note**: Openai-compatible local servers (Ollama, LM Studio, llama.cpp) are addressable via LiteLLM routing with `--openai-api-base <local-url>` and a LiteLLM model prefix such as `openai/<model-id>`. Same connector class as OpenAI — no separate vendor needed.
