# Codex Provider — P1 Vendor Verification Evidence (RV353 Corrected)

<a name="codex-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `codex` |
| upstream-id | openai/codex (GitHub) |
| tool-version | 0.87.0 |
| verified-at | 2026-07-13 UTC (RV353 correction) |
| evidence-kind | installed-tool CLI probe (`codex --version`, `codex --help`, `codex login --help`), global/project config inspection, `-c` config override acceptance test |
| **correction-note** | RV353 finding #3: version corrected to 0.87.0 (was "CLI installed; exact version not returned"). Config override parsing ≠ wire compatibility proof. Non-OpenAI vendor support via model_providers requires isolated launch verification; Anthropic/Google/OpenRouter remain custom-entries with unverified execution. Project-scope precedence NOT verified. |

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
| **Model config shape** | Top-level `model = "<id>"` selects active model. `[model_providers.<id>]` block: `name`, `base_url`, `env_key` (env var reference), `wire_api`, plus `model`/`model_provider` for selection. |
| **Project-scope precedence** | **NOT verified** — global config may override project-local settings. This is the key blocker for automation: if AG writes to project `.codex/config.toml` but Codex reads only `~/.codex/config.toml`, the writer produces no effect. |
| **Reload behavior** | Codex reads config at startup; no live reload observed. Changes require restart. |

---

## Projection mode implications for AG

- **Custom-entries (config)**: Primary path for non-OpenAI vendors, BLOCKED on project-scope verification. Write `[model_providers.<id>]` entries into project `.codex/config.toml`. Until project-scope precedence is verified, this remains `blocked`. If global config wins exclusively, AG would need user consent to write `~/.codex/config.toml` (requires consent gate).
- **CLI override**: Secondary path. Use `-c 'model_providers.test.name="..."' -m "test/model-id"` at launch time. This WORKS for parsing but does not prove wire compatibility or successful execution against non-OpenAI endpoints.
- **Native-key-injection**: Not applicable — Codex uses vendor account (OpenAI) or model_providers config. No ambient env var key injection for native vendors.
