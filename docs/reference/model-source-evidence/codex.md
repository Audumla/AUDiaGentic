# Codex Provider — P1 Vendor Verification Evidence (RV353 Corrected)

<a name="codex-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `codex` |
| upstream-id | openai/codex (GitHub) |
| tool-version | 0.87.0 (installed); upstream docs reference v0.134+ features |
| verified-at | 2026-07-16 UTC (RV353 correction + upstream doc revalidation) |
| evidence-kind | installed-tool CLI probe (`codex --version`, `codex --help`, `codex login --help`), global/project config inspection, `-c` config override acceptance test, upstream doc verification (config-basic, config-advanced, config-reference) |
| **correction-note** | RV353 finding #3: version corrected to 0.87.0 (was "CLI installed; exact version not returned"). Config override parsing ≠ wire compatibility proof. Non-OpenAI vendor support via model_providers requires isolated launch verification; Anthropic/Google/OpenRouter remain custom-entries with unverified execution. Project-scope precedence NOT verified. **2026-07-16 revalidation**: upstream docs (v0.134+) expose profiles, Amazon Bedrock built-in, Azure provider, auth commands, HTTP headers, model catalog, shell environment policy, auto review, hooks, network proxy — none of these are installed-version-verified yet.

---

## Local endpoint support (openai-compatible connector)

Codex can connect to local/remote openai-compatible endpoints (Ollama, LM Studio, llama.cpp, vLLM, LlamaSwap) through two paths — both use the `openai-compatible` connector class, not a separate vendor.

### Built-in local providers (Ollama, LM Studio)

Codex exposes `--oss --local-provider <provider>` as first-class CLI flags. Built-in provider IDs: `ollama`, `lmstudio`. These are convenience shims for the common case of running an openai-compatible server locally.

```
codex --oss --local-provider ollama -m gpt-oss:20b
codex --oss --local-provider lmstudio -m gpt-oss-20b
```

Or set defaults in `~/.codex/config.toml`:

```toml
model = "gpt-oss:20b"
model_provider = "ollama"
oss_provider = "ollama"

model_context_window = 131072
model_reasoning_effort = "medium"
```

On Windows the config path is `%USERPROFILE%\.codex\config.toml`. Both Codex CLI and the VS Code extension share this file.

### Custom model_providers entries

For arbitrary openai-compatible endpoints (remote llama.cpp, LlamaSwap-routed hosts, vLLM), define a custom provider in config.toml:

```toml
model = "gpt-oss-20b"
model_provider = "local_llama"

[model_providers.local_llama]
name = "Local llama.cpp"
base_url = "http://10.10.100.10:42001/v1"
wire_api = "responses"
# optional auth:
env_key = "LOCAL_LLM_API_KEY"
```

Replace `model`, `base_url`, and `env_key` with your actual values.

### Wire API constraint (important)

Codex now **requires** the OpenAI Responses API (`POST /v1/responses`). It no longer accepts providers that only implement `POST /v1/chat/completions`. The config key is `wire_api = "responses"` — this is the only value currently accepted.

Recent llama.cpp builds provide `/v1/responses` (internally translating to Chat Completions), but there have been compatibility bugs with Codex tool-result and reasoning payloads on older builds. Use a recent build.

Test your endpoint before configuring:

```bash
curl http://10.10.100.10:42001/v1/responses \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-oss-20b",
    "input": "Reply with the word working"
  }'
```

| Field | Value |
|---|---|
| **Connector class** | `openai-compatible` (same as OpenAI) |
| **Config surface** | `~/.codex/config.toml` or project `.codex/config.toml`; CLI `-c` overrides at runtime |
| **Built-in local providers** | `ollama`, `lmstudio` — accessed via `--oss --local-provider <id>` or `oss_provider = "<id>"` in config |
| **Custom providers** | `[model_providers.<id>]` blocks with `name`, `base_url`, `wire_api = "responses"`, optional `env_key` |
| **Wire API requirement** | OpenAI Responses API only (`wire_api = "responses"`) — chat completions alone is insufficient |

---

## Vendor: OpenAI

<a name="codex-openai"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `codex --version` returns 0.87.0. Global `~/.codex/config.toml` shows `model = "gpt-5.6-terra"` (OpenAI model). CLI help shows `-m, --model <MODEL>` flag. Codex's native vendor is OpenAI — the agent runs on an OpenAI account/subscription via `codex login`. |
| **Sanitized summary** | OpenAI is Codex's native vendor — accessed through a vendor account/login path (`codex login`), not injectable API key. Model selected via `model` field in config or `-m` CLI flag. To use a specific OpenAI model: set `model = "openai/<id>"` in config or pass `-m <id>`. No env var key injection needed — Codex uses its own authentication flow (vendor account). |
| **Support state** | **verified native (vendor account via login; no key injection)** |

---

## Vendor: Anthropic

<a name="codex-anthropic"></a>

| Field | Value |
|---|---|
| **Sanitized source** | CLI `-c` override accepts `model_providers.<id>.base_url="..."` syntax, confirming `[model_providers]` is a valid config path. No pre-configured Anthropic entry in global or project config. Wire API compatibility with Anthropic's API surface NOT verified — config parsing acceptance does not prove runtime execution. |
| **Sanitized summary** | Anthropic support REQUIRES a `[model_providers.<id>]` entry with `base_url`, `env_key` (for API key reference), `wire_api = "chat"` or similar. The `-c 'model_providers.anthropic.base_url="https://api.anthropic.com/v1"'` override syntax is accepted by the CLI, confirming the config PATH exists. However: (a) whether Anthropic's wire API is compatible with Codex's expectations is unverified; (b) project-scope `.codex/config.toml` precedence over global config is NOT verified; (c) authenticated execution has not been tested. |
| **Support state** | **blocked: config path exists but wire compatibility, project-scope precedence, and execution all unverified** |

---

## Vendor: Google (Gemini)

<a name="codex-google"></a>

| Field | Value |
|---|---|
| **Sanitized source** | Same `model_providers` config path as Anthropic. No pre-configured Google entry in any inspected config. Wire API compatibility NOT verified. |
| **Sanitized summary** | Google/Gemini support via the same `[model_providers.<id>]` mechanism: base_url, env_key reference for API key, wire_api compatibility flag. All three conditions unverified: (a) wire API compatibility with Gemini's endpoint; (b) project-scope config precedence; (c) authenticated execution test. |
| **Support state** | **blocked: config path exists but wire compatibility, project-scope precedence, and execution all unverified** |

---

## Vendor: OpenRouter

<a name="codex-openrouter"></a>

| Field | Value |
|---|---|
| **Sanitized source** | Same `model_providers` config path. No pre-configured OpenRouter entry. |
| **Sanitized summary** | OpenRouter support via the same `[model_providers.<id>]` mechanism with OpenAI-compatible base URL (`https://openrouter.ai/api/v1`) and API key reference. The wire_api would be `"chat"` (OpenAI chat completions), which has higher compatibility likelihood, but still unverified: no isolated launch test exists. |
| **Support state** | **blocked: config path exists but project-scope precedence and execution unverified** |

---

## Config surface

| Field | Value |
|---|---|
| **Config file** | `~/.codex/config.toml` (user-global, primary authority) AND `.codex/config.toml` (project-local, managed by repo for MCP/LSP). CLI `-c key=value` overrides at runtime — model_providers entries accepted with full schema (`name`, `base_url`, `env_key`, `wire_api` required). Project-scope precedence over global config: NOT verified — critical unknown for automation path. The `-c` flag successfully injected a test provider entry (passed validation, failed on non-terminal stdin), confirming runtime override works. |
| **Model config shape** | Top-level `model = "<id>"` selects active model. `[model_providers.<id>]` block: `name`, `base_url`, `env_key` (env var reference), `wire_api`, plus `model`/`model_provider` for selection. For local endpoints: `oss_provider = "ollama"|"lmstudio"` + `model_provider = "ollama"|"lmstudio"` for built-in providers; `[model_providers.<id>]` for custom openai-compatible endpoints with `wire_api = "responses"`. |
| **Project-scope precedence** | **NOT verified** — global config may override project-local settings. This is the key blocker for automation: if AG writes to project `.codex/config.toml` but Codex reads only `~/.codex/config.toml`, the writer produces no effect. |
| **Reload behavior** | Codex reads config at startup; no live reload observed. Changes require restart. After restarting VS Code, the extension inherits the updated configuration. |
| **Local providers** | Built-in `--oss --local-provider ollama|lmstudio`; custom `[model_providers.<id>]` with `wire_api = "responses"`. All are openai-compatible connector class, not a separate vendor. |

---

## New upstream capabilities (v0.134+, NOT installed-version-verified)

The following were confirmed against upstream documentation at `https://developers.openai.com/codex/config-basic`, `config-advanced`, and `config-reference`. These require installed-version verification before any automation.

### Profiles

Profiles enable named configuration layers selected via `--profile profile-name`. Profile file: `~/.codex/profile-name.config.toml`. In v0.134+, `--profile` no longer reads `[profiles.profile-name]` from `config.toml`; legacy profile tables must be migrated to separate files.

```toml
# ~/.codex/deep-review.config.toml
model = "gpt-5.5"
model_reasoning_effort = "xhigh"
approval_policy = "on-request"
model_catalog_json = "/Users/me/.codex/model-catalogs/deep-review.json"
```

### Amazon Bedrock built-in provider

Codex includes a built-in `amazon-bedrock` model provider with AWS profile and region overrides:

```toml
model_provider = "amazon-bedrock"
model = "<bedrock-model-id>"

[model_providers.amazon-bedrock.aws]
profile = "default"
region = "eu-central-1"
```

### Azure provider

Azure supports `query_params`, retry tuning, and stream idle timeout:

```toml
[model_providers.azure]
name = "Azure"
base_url = "https://YOUR_PROJECT_NAME.openai.azure.com/openai"
env_key = "AZURE_OPENAI_API_KEY"
query_params = { api-version = "2025-04-01-preview" }
wire_api = "responses"
request_max_retries = 4
stream_max_retries = 10
stream_idle_timeout_ms = 300000
```

### Auth command (bearer token via external process)

Command-backed authentication for fetching tokens from credential helpers:

```toml
[model_providers.proxy]
name = "OpenAI using LLM proxy"
base_url = "https://proxy.example.com/v1"
wire_api = "responses"

[model_providers.proxy.auth]
command = "/usr/local/bin/fetch-codex-token"
args = ["--audience", "codex"]
timeout_ms = 5000
refresh_interval_ms = 300000
```

Do not combine `[model_providers.<id>.auth]` with `env_key`, `experimental_bearer_token`, or `requires_openai_auth`.

### HTTP headers on model providers

Static and environment-variable-backed headers:

```toml
[model_providers.example]
http_headers = { "X-Example-Header" = "example-value" }
env_http_headers = { "X-Example-Features" = "EXAMPLE_FEATURES" }
```

### Data residency (OpenAI built-in provider override)

For data-residency-enabled projects, use `openai_base_url` instead of defining a new provider:

```toml
openai_base_url = "https://us.api.openai.com/v1"
```

Project-local `.codex/config.toml` cannot override `openai_base_url` — this is blocked for security.

### Model catalog JSON

Custom model catalog via `model_catalog_json`. Profile files can override per-profile:

```toml
model_catalog_json = "/Users/me/.codex/model-catalogs/deep-review.json"
```

### Shell environment policy

Controls which environment variables Codex forwards to spawned commands:

```toml
[shell_environment_policy]
inherit = "none"
set = { PATH = "/usr/bin", MY_FLAG = "1" }
ignore_default_excludes = false
exclude = ["AWS_*", "AZURE_*"]
include_only = ["PATH", "HOME"]
```

### Auto review

Route eligible interactive approval requests through automatic review:

```toml
approvals_reviewer = "auto_review"  # Or "user"
approval_policy = "on-request"

[auto_review]
policy = "Use your organization's automatic review policy."
```

### Lifecycle hooks (inline TOML)

Hooks can be configured inline in `config.toml` alongside `hooks.json`:

```toml
[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/pre_tool_use_policy.py"'
timeout = 30
statusMessage = "Checking Bash command"
```

### Network proxy (sandboxed networking)

Experimental sandboxed networking with domain policies:

```toml
[features.network_proxy]
enabled = true
domains = { "example.com" = "allow", "*.internal.corp" = "deny" }
```

### Personality and reasoning summary

Communication style and reasoning summary controls:

```toml
personality = "friendly"  # or "pragmatic" or "none"
model_reasoning_summary = "none"  # or "auto", "concise", "detailed"
```

### Config precedence (updated)

1. CLI flags and `--config` overrides
2. Project config files: `.codex/config.toml` (closest wins; trusted projects only)
3. Profile files selected with `--profile profile-name`
4. User config: `~/.codex/config.toml`
5. System config: `/etc/codex/config.toml`
6. Built-in defaults

Project-local `.codex/config.toml` cannot override: `openai_base_url`, `chatgpt_base_url`, `apps_mcp_product_sku`, `model_provider`, `model_providers`, `notify`, `profile`, `profiles`, `experimental_realtime_ws_base_url`, `otel`.

---

## Projection mode implications for AG

- **Custom-entries (config)**: Primary path for non-OpenAI vendors AND local openai-compatible endpoints, BLOCKED on project-scope verification. Write `[model_providers.<id>]` entries into project `.codex/config.toml`. Until project-scope precedence is verified, this remains `blocked`. If global config wins exclusively, AG would need user consent to write `~/.codex/config.toml` (requires consent gate). For local endpoints: built-in `oss_provider = "ollama"|"lmstudio"` shims require no `[model_providers]` block; custom openai-compatible servers use `[model_providers.<id>]` with `wire_api = "responses"`. Wire API constraint: Codex requires OpenAI Responses API — chat-completions-only endpoints will not work.
- **CLI override**: Secondary path. Use `-c 'model_providers.test.name="..."' -m "test/model-id"` at launch time. This WORKS for parsing but does not prove wire compatibility or successful execution against non-OpenAI endpoints.
- **Native-key-injection**: Not applicable — Codex uses vendor account (OpenAI) or model_providers config. No ambient env var key injection for native vendors.
- **Local endpoint note**: Ollama, LM Studio, llama.cpp are all `openai-compatible` connector class — not a separate vendor. They use the same `[model_providers.<id>]` mechanism as any openai-compatible endpoint, with built-in shims (`--oss --local-provider`) for convenience.
