# OpenHands Provider — P1 Vendor Verification Evidence (RV353 Corrected)

<a name="openhands-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `openhands` |
| upstream-id | OpenHands/OpenHands (Agent Canvas) + OpenHands/software-agent-sdk |
| tool-version | Agent Canvas 1.46.2 (latest release Jul 15, 2026); SDK separate package; CLI legacy |
| verified-at | 2026-07-13 UTC (RV353 correction), 2026-07-16 UTC (upstream doc revalidation) |
| evidence-kind | installed-tool CLI probe (`openhands --help`, `openhands mcp --help`), project config inspection (`.openhands/config.toml`), upstream docs verification (docs.openhands.dev) |
| **correction-note** | RV353 finding #5: prior classification "verified native via LiteLLM" for all P1 vendors conflated env var recognition with execution proof. The tool accepts LLM_API_KEY/LLM_BASE_URL/LLM_MODEL env vars and parses model prefixes, but no isolated authenticated launch test exists against any vendor endpoint. Change wording to "verified launch-env route" — the mechanism is accepted at startup, not proven to execute successfully. **2026-07-16 revalidation**: OpenHands has been fundamentally restructured. Agent Canvas is now a developer control center that runs multiple agents (OpenHands, Claude Code, Codex, Gemini CLI) via ACP (Agent Client Protocol). The old CLI/GUI config.toml approach is legacy V0. New architecture: Settings UI in Web app drives LLM configuration; LLM Provider dropdown + model dropdown + API Key field; advanced settings support custom models with provider prefix and base URL; up to 10 LLM profiles per account switchable mid-conversation; Agent SDK handles all LLM orchestration. ACP agents authenticate via subscription login or API key (ANTHROPIC_API_KEY for Claude, OPENAI_API_KEY for Codex, GEMINI_API_KEY for Gemini). Config.toml is legacy V0 only.

---

## Vendor: OpenAI

<a name="openhands-openai"></a>

| Field | Value |
|---|---|
| **Sanitized source** | `openhands --help` shows env var override: `(LLM_API_KEY, LLM_BASE_URL, LLM_MODEL)`; model format uses LiteLLM prefix convention (e.g., `openai/gpt-4o`). Project `.openhands/config.toml` exists with `[mcp_servers]` blocks but no `[llm]` section. SDK deprecation warning for authlib.jose observed during help render. |
| **Sanitized summary** | OpenAI is supported via LiteLLM model prefix (`openai/<model-id>`). Key injection mechanism: set `LLM_API_KEY=<key>`, `LLM_BASE_URL=<optional-override>`, `LLM_MODEL=openai/<model-id>` with `--override-with-envs` flag. The env vars are RECOGNIZED by the tool's startup logic. Config fallback: structured `[llm]` section in `.openhands/config.toml` with `model`, `api_key`, `base_url` fields — exact key names inferred from SDK docs (not verified against installed version). Model granularity: **single model at a time** per session. |
| **Support state** | **verified launch-env route** (env var recognition confirmed; execution proof requires authenticated launch test) |

---

## Vendor: Anthropic

<a name="openhands-anthropic"></a>

| Field | Value |
|---|---|
| **Sanitized source** | OpenHands SDK documentation references LiteLLM abstraction layer. Help text confirms `LLM_API_KEY` + model prefix pattern for all vendors. |
| **Sanitized summary** | Anthropic is supported via LiteLLM model prefix (`anthropic/<model-id>`). Same env var mechanism: `LLM_API_KEY=<anthropic-key>`, `LLM_MODEL=anthropic/<id>`. OpenHands SDK's LiteLLM integration handles the vendor-specific API translation. Model granularity: **single model at a time**. |
| **Support state** | **verified launch-env route** (env var recognition confirmed via LiteLLM abstraction; execution proof requires authenticated launch test) |

---

## Vendor: Google (Gemini)

<a name="openhands-google"></a>

| Field | Value |
|---|---|
| **Sanitized source** | Same LiteLLM abstraction. Help text confirms unified `LLM_API_KEY` pattern for all vendors. |
| **Sanitized summary** | Google/Gemini is supported via LiteLLM model prefix (`gemini/<model-id>` or `google/<model-id>` — exact prefix convention depends on LiteLLM version). Same env var mechanism: `LLM_API_KEY=<gemini-key>`, `LLM_MODEL=gemini/<id>`. Model granularity: **single model at a time**. |
| **Support state** | **verified launch-env route** (env var recognition confirmed via LiteLLM abstraction; execution proof requires authenticated launch test) |

---

## Vendor: OpenRouter

<a name="openhands-openrouter"></a>

| Field | Value |
|---|---|
| **Sanitized source** | Same LiteLLM abstraction. Help text confirms unified `LLM_API_KEY` pattern. |
| **Sanitized summary** | OpenRouter is supported via LiteLLM model prefix (`openrouter/<vendor>/<model-id>`). Same env var mechanism: `LLM_API_KEY=<openrouter-key>`, `LLM_MODEL=openrouter/<id>`. Model granularity: **single model at a time**. |
| **Support state** | **verified launch-env route** (env var recognition confirmed via LiteLLM abstraction; execution proof requires authenticated launch test) |

---

## Config surface

| Field | Value |
|---|---|
| **Config file** | `.openhands/config.toml` (project-local, managed by repo descriptor for MCP). Current project config has `[mcp_servers]` blocks only — NO `[llm]` section present. |
| **Structured config shape** | `[llm]` section expected with `model`, `api_key`, `base_url` fields — exact key names inferred from SDK docs; env vars take precedence with `--override-with-envs`. The structured config path is unverified against the installed version. |
| **Env var keys** | `LLM_API_KEY` (unified for all vendors), `LLM_BASE_URL` (optional override), `LLM_MODEL` (vendor-prefixed model id, e.g. `openai/gpt-4o`). These env vars are recognized by the startup flag — they may be passed through to LiteLLM without execution verification. |
| **Single-model semantics** | OpenHands binds one active model at a time — not a multi-model catalog. "Enabling a vendor" means selecting one model. |

---

## New upstream architecture (verified 2026-07-16 from docs.openhands.dev)

### Agent Canvas — developer control center

OpenHands has been fundamentally restructured. The new primary product is **Agent Canvas**, a browser-based UI and backend server for running agents and automations. It runs multiple agents:
- Built-in **OpenHands** agent (the native OpenHands SDK agent)
- External **ACP agents**: Claude Code, Codex, Gemini CLI via Agent Client Protocol

### ACP (Agent Client Protocol)

The [Agent Client Protocol](https://agentclientprotocol.com/protocol/overview) is a standard for talking to coding agents over JSON-RPC on stdio. Instead of Agent Canvas calling an LLM directly, the Agent Server spawns the agent's own CLI as a subprocess and relays each turn to it.

**Supported ACP providers:**

| Provider | Default Command |
|---|---|
| Claude Code | `npx -y @agentclientprotocol/claude-agent-acp` |
| Codex | `npx -y @zed-industries/codex-acp` |
| Gemini CLI | `npx -y @google/gemini-cli --acp` |

### ACP agent authentication (two paths)

ACP agents authenticate **two ways: subscription login, or API key** — and the onboarding fields are optional. Subscription login takes priority over API key.

| Provider | Subscription login | API key |
|---|---|---|
| Claude Code | macOS Keychain or `~/.claude/.credentials.json` | `ANTHROPIC_API_KEY` |
| Codex | `~/.codex/auth.json` (ChatGPT login) | `OPENAI_API_KEY` |
| Gemini CLI | `~/.gemini/oauth_creds.json` | `GEMINI_API_KEY` |

### New Settings UI (V1)

Configuration is now UI-driven in the Web app. The LLM settings page provides:
- **LLM Provider** dropdown (Anthropic, OpenAI, Mistral AI, OpenHands provider, etc.)
- **LLM Model** dropdown
- **API Key** field
- **Advanced** toggle for custom models with provider prefix, base URL

### LLM profiles

Up to 10 LLM profiles per account. Switchable mid-conversation without losing context. Profiles auto-created on save; the `/model` slash command lists and switches profiles. The `SwitchLLMTool` allows the agent itself to select models dynamically.

### LiteLLM integration unchanged

Under the hood, OpenHands still uses LiteLLM for LLM orchestration. Any model supported by LiteLLM can be connected via the custom model field. Provider-specific env vars like `LLM_API_VERSION`, `LLM_EMBEDDING_MODEL` can be set as environment variables.

### Legacy V0

The old `config.toml` / CLI approach is legacy V0. The `[llm]` section with `model`, `api_key`, `base_url` fields has been superseded by the Settings UI. Environment variable configuration still works for self-hosted deployments (`LLM_API_KEY`, `LLM_MODEL`).

---

## ACP status

| Field | Value |
|---|---|
| **ACP support** | None (not listed in registry) |
| **Registry ID** | N/A — not in ACP registry v1.0.0 |

OpenHands is not currently listed in the ACP registry v1.0.0. No ACP adapter package exists for this provider.

## Config override at startup

| Field | Value |
|---|---|
| **CLI flag** | No documented `--config` flag |
| **Env var** | No documented env var for config override |

OpenHands does not support startup config override.

---

## Projection mode implications for AG

- **Native-key-injection (env)**: Primary viable path. Set `LLM_API_KEY`, `LLM_BASE_URL` (if custom endpoint), and `LLM_MODEL` at launch time with `--override-with-envs`. This is the documented key-injection vehicle. Env var recognition is verified; actual vendor execution against non-OpenAI endpoints requires authenticated launch test to fully validate.
- **Custom-entries**: Not applicable — OpenHands does not carry a model catalog; it binds one model via env or `[llm]` config.
- **Structured config**: Secondary path (BLOCKED on [llm] key verification). AG could write `[llm]` section into `.openhands/config.toml`, but exact key names and SDK acceptance need isolated test against the installed version.
- **Local endpoint note**: Openai-compatible local servers (Ollama, LM Studio, llama.cpp) are addressable via `LLM_BASE_URL=<local-url>` with `--override-with-envs` and a LiteLLM model prefix such as `openai/<model-id>`. Same connector class as OpenAI — no separate vendor needed.
