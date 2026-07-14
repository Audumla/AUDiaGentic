# OpenHands Provider — P1 Vendor Verification Evidence (RV353 Corrected)

<a name="openhands-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `openhands` |
| upstream-id | All-Hands-AI/OpenHands (software-agent-sdk) |
| tool-version | CLI 1.16.0 / SDK 1.21.0 |
| verified-at | 2026-07-13 UTC (RV353 correction) |
| evidence-kind | installed-tool CLI probe (`openhands --help`, `openhands mcp --help`), project config inspection (`.openhands/config.toml`) |
| **correction-note** | RV353 finding #5: prior classification "verified native via LiteLLM" for all P1 vendors conflated env var recognition with execution proof. The tool accepts LLM_API_KEY/LLM_BASE_URL/LLM_MODEL env vars and parses model prefixes, but no isolated authenticated launch test exists against any vendor endpoint. Change wording to "verified launch-env route" — the mechanism is accepted at startup, not proven to execute successfully. |

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

## Projection mode implications for AG

- **Native-key-injection (env)**: Primary viable path. Set `LLM_API_KEY`, `LLM_BASE_URL` (if custom endpoint), and `LLM_MODEL` at launch time with `--override-with-envs`. This is the documented key-injection vehicle. Env var recognition is verified; actual vendor execution against non-OpenAI endpoints requires authenticated launch test to fully validate.
- **Custom-entries**: Not applicable — OpenHands does not carry a model catalog; it binds one model via env or `[llm]` config.
- **Structured config**: Secondary path (BLOCKED on [llm] key verification). AG could write `[llm]` section into `.openhands/config.toml`, but exact key names and SDK acceptance need isolated test against the installed version.
