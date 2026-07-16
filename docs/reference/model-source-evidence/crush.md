# Crush Provider — P1 New Candidate Evidence

<a name="crush-evidence"></a>

## Record header

| Field | Value |
|---|---|
| provider-id | `crush` |
| upstream-id | charmbracelet/crush (GitHub) |
| tool-version | probe-required |
| verified-at | 2026-07-16 UTC |
| evidence-kind | upstream documentation review (config examples, provider types, local support) |

---

## Provider configuration

Crush uses a JSON config with `providers` top-level key. Provider types include local server adapters and OpenAI-compatible endpoints.

### Provider types

Upstream documents these provider type values:

| Type | Description |
|---|---|
| `llamacpp` | llama.cpp HTTP server |
| `lmstudio` | LM Studio HTTP server |
| `litellm` | LiteLLM proxy |
| `ollama` | Ollama OpenAI-compatible shim |

### Example local provider

```json
{
  "providers": {
    "local-llama": {
      "name": "Local llama.cpp",
      "base_url": "http://127.0.0.1:8080/v1/",
      "type": "llamacpp"
    }
  }
}
```

### Model autodiscovery

Crush supports model autodiscovery for local providers — the provider can fetch available models from the server's `/v1/models` endpoint. However, deterministic profile validation requires persisting an explicit filtered model list.

---

## Config surface (upstream-only facts)

| Field | Value |
|---|---|
| **Config format** | JSON |
| **Config location** | Probe-required — project-scoped path and user-global path both need verification |
| **Provider block shape** | `{providers: {<id>: {name, base_url, type}}}` |
| **Model config shape** | Autodiscovered or explicit list — exact schema probe-required |
| **Key mechanism** | API key reference syntax probe-required |

---

## Wire/protocol capabilities (expected)

| Capability | Support |
|---|---|
| OpenAI Chat Completions | Yes (local adapters + openai-compatible) |
| OpenAI Responses API | Probe required |
| Anthropic Messages | Provider dependent (via litellm or gateway) |
| Gemini native | Provider dependent (via litellm or gateway) |

---

## Projection mode implications for AG

- **Custom-entries**: Primary path. Write `{providers: {<id>: {...}}}` into project or user config. BLOCKED until exact path, precedence, key-reference syntax, and reload behavior are verified.
- **Discovery**: Crush can autodiscover models from local endpoints, but AG should persist a filtered explicit list for deterministic profile validation.
- **Priority**: P1 after shared JSON managed-config support lands. Do not add special-case writer before the contract exists.

---

## Open validation items

| Item | Status |
|---|---|
| Exact project vs global config path and precedence | probe-required |
| API key reference syntax (env var, inline, or external) | probe-required |
| Explicit-model vs autodiscovery merge behavior | probe-required |
| Hot reload/restart requirement after config change | probe-required |
| Wire API compatibility per provider type | probe-required |
