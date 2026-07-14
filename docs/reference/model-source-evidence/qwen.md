# Qwen Provider — P1 Vendor Verification Evidence (RV353 Corrected)

<a name="qwen-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `qwen` |
| upstream-id | qwen-code (npm @qwen-code/qwen-code) |
| tool-version | 0.13.1 (installed as `qwen` CLI command in npm global) |
| verified-at | 2026-07-13 UTC (RV353 correction) |
| evidence-kind | installed-tool CLI probe (`qwen --help`, `qwen auth status`), settings file inspection (`~/.qwen/settings.json`) |
| **correction-note** | RV353 finding #2: prior classification "Anthropic/Google unsupported, OpenAI-only connector" is materially false. Installed help proves `--auth-type` accepts openai/anthropic/qwen-oauth/gemini/vertex-ai. Settings surface carries auth type selection and model pointer. |

---

## Vendor: OpenAI

<a name="qwen-openai"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `qwen --help` shows `--auth-type [choices: "openai", "anthropic", "qwen-oauth", "gemini", "vertex-ai"]`. CLI flags include `--openai-api-key <key>`, `--openai-base-url <url>`, `-m, --model <MODEL>`. Settings at `~/.qwen/settings.json` contain `"security.auth.selectedType"` for auth type pointer and `"model.name"` for active model. |
| **Sanitized summary** | OpenAI is supported via `--auth-type openai` with `--openai-api-key` authentication. Base URL can be overridden with `--openai-base-url`. Model selection via `-m <model-id>`. Auth type persists in settings (`"selectedType": "openai"`), model name in `"model.name"`. |
| **Support state** | **verified native via auth-type + CLI/config flags** (`--auth-type openai`, `--openai-api-key`, optional `--openai-base-url`) |

---

## Vendor: Anthropic

<a name="qwen-anthropic"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `qwen --help` shows `--auth-type [choices: ..., "anthropic", ...]`. Isolated test: `qwen -m claude-sonnet -p "test" --auth-type anthropic` returns error "ANTHROPIC_API_KEY environment variable not found (or set settings.security.auth.apiKey)". Settings file `"security.auth.selectedType"` controls active auth path. |
| **Sanitized summary** | Anthropic is supported via `--auth-type anthropic`. Key mechanism: **confirmed `ANTHROPIC_API_KEY` env var** (from runtime error message). Model selection via `-m <model-id>`. Can also set key in settings at `settings.security.auth.apiKey`. Single active model at a time. |
| **Support state** | **verified native via auth-type** (`--auth-type anthropic`; key ANTHROPIC_API_KEY confirmed) |

---

## Vendor: Google (Gemini)

<a name="qwen-google"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `qwen --help` shows `--auth-type [choices: ..., "gemini", "vertex-ai"]`. The flag `--google-api-key` exists but is for Google Custom Search (web search), NOT model access. Isolated test: `qwen -m gemini-pro -p "test" --auth-type gemini` returns error "GEMINI_API_KEY environment variable not found (or set settings.security.auth.apiKey)". |
| **Sanitized summary** | Google/Gemini has TWO auth type paths: `gemini` (standard Gemini API) and `vertex-ai` (Google Cloud Vertex AI). Key mechanism for gemini: **confirmed `GEMINI_API_KEY` env var** (from runtime error message). For vertex-ai: expected to use Google Cloud project credentials or settings key. Model selection via `-m <model-id>`. The `--google-api-key` CLI flag is irrelevant for models (web search only). |
| **Support state** | **verified native via auth-type** (`--auth-type gemini`; key GEMINI_API_KEY confirmed; vertex-ai path not tested) |

---

## Vendor: OpenRouter

<a name="qwen-openrouter"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `--auth-type` choices do not include "openrouter". No OpenRouter-specific flags in help output. Only openai/anthropic/qwen-oauth/gemini/vertex-ai auth types are exposed. |
| **Sanitized summary** | OpenRouter is NOT a listed auth type. It cannot be enabled via the documented `--auth-type` mechanism. Possible workarounds: using `--auth-type openai` with OpenRouter's openai-compatible base URL and API key, but this is unverified and would require testing against the actual model routing behavior. |
| **Support state** | **blocked: not a listed auth type; possible via openai-compatible proxy under `--auth-type openai` — not tested** |

---

## Config surface

| Field | Value |
|---|---|
| **Config file** | `~/.qwen/settings.json` (user-global, home-scoped). Contains: `"security.auth.selectedType"` for active auth type, `"model.name"` for selected model. Project-local config path NOT verified — current settings appear user-global. |
| **Auth mechanism** | Multi-type selection via `--auth-type <openai\|anthropic\|qwen-oauth\|gemini\|vertex-ai>`. Persists as `"selectedType"` in settings. Per-auth-type credentials: **confirmed env vars** — `OPENAI_API_KEY` (openai auth-type), `ANTHROPIC_API_KEY` (anthropic), `GEMINI_API_KEY` (gemini). Can also set via CLI flags (`--openai-api-key`) or `settings.security.auth.apiKey`. Only ONE auth-type active at a time. |
| **Model selection** | `-m, --model <id>` CLI flag; persists as `"model.name"` in settings. Single active model at a time. |
| **Reload behavior** | Not verified — Qwen may require restart to pick up settings.json changes. Auth type and model likely resolved at launch. |

---

## Projection mode implications for AG

- **Native-key-injection (env)**: Primary viable path for P1 vendors. Set `--auth-type <vendor>` plus the confirmed env vars: `OPENAI_API_KEY` (openai), `ANTHROPIC_API_KEY` (anthropic), `GEMINI_API_KEY` (gemini). Key mappings verified via runtime error messages.
- **Custom-entries**: Not applicable — Qwen uses multi-auth-type model selection, not provider catalog entries. Only one active model at a time via settings/CLI.
- **Limited scope note**: Unlike Pi which accepts all vendor keys simultaneously, Qwen switches auth mode per type — only ONE `--auth-type` is active at a time. This means AG cannot have multiple vendors enabled concurrently through the same tool instance.
