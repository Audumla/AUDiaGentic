# Per-Harness Provider Capability Matrix

Status: authoritative reference candidate  
Last validated: 2026-07-17  
Planning set: `docs/planning/active/ptm-telemetry/PT01..PT02`

This document catalogs what each coding agent harness can do with providers — not just "can it connect to OpenRouter?" but "can AUDiaGentic monitor, budget, and intelligently schedule work across providers through this harness?"

The scheduling layer is where the real differences between harnesses become apparent.

## Matrix overview

For each harness, four dimensions are evaluated:

1. **Provider connectivity** — which providers can it talk to
2. **Authentication** — how credentials are managed
3. **Endpoint configuration** — what flexibility exists for routing and failover
4. **Telemetry** — what budget, quota, and session data is available

## Connectivity table

### Harness provider support

| Harness | Anthropic | OpenAI | OpenRouter | Gemini | Azure OpenAI | Ollama | llama.cpp | LM Studio | vLLM | LiteLLM | Local OpenAI compat | Custom endpoint |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Claude Code | Native | No | No | No | No | No | No | No | No | No | No | No |
| Codex CLI | Gateway (Responses) | Native | Custom (Responses only) | Gateway (Responses) | Yes | Ollama/LM Studio | No | LM Studio | No | No | Yes | Yes |
| OpenCode | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Goose | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Qwen Code | Yes (Anthropic SDK) | Yes | Yes | Yes (Google SDK) | Yes | Yes | Yes | Yes | Yes | No | Yes | Yes |
| Continue | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Pi | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | No | Yes | Yes |
| Zed | Yes | Yes | Yes | Native | Yes | Native | Native | Native | No | No | Yes | Yes |
| Aider | LiteLLM only | Native/LiteLLM | LiteLLM only | LiteLLM only | LiteLLM only | Yes | No | No | No | Yes | Yes | Yes |
| Cline | Yes (OpenRouter) | Yes | Native | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |
| Crush | Via litellm | Native | Via litellm | Via litellm | Via litellm | Native | Native | Native | No | Native | Yes | Yes |
| Kilo Code | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | No | No | Yes | Yes |
| OpenHands | LiteLLM/ACP | LiteLLM/ACP | LiteLLM/ACP | LiteLLM/ACP | LiteLLM/ACP | LiteLLM/ACP | No | No | No | LiteLLM | LiteLLM/ACP | LiteLLM/ACP |
| Cursor | Subscription | Subscription | No | No | No | No | No | No | No | No | No | No |
| Roo | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes |

### Authentication mechanisms

| Harness | API key | OAuth | Subscription login | Browser login | PAT | Local only |
|---|---:|---:|---:|---:|---:|---:|
| Claude Code | No | Yes | Yes | Yes | No | No |
| Codex CLI | Yes | No | Yes | No | No | Ollama/LM Studio |
| OpenCode | Yes | Yes | Yes | Yes | No | Yes |
| Goose | Yes | Yes | Yes | No | No | Yes |
| Qwen Code | Yes (env refs) | No | No | No | No | Yes |
| Continue | Yes | No | No | No | No | Yes |
| Pi | Yes | No | No | No | No | Yes |
| Zed | Keychain/env | No | Yes | No | No | Native (Ollama, LM Studio, llama.cpp) |
| Aider | Yes | No | No | No | No | Ollama |
| Cline | Yes | Yes | No | No | No | Yes |
| Crush | Yes | No | No | No | No | Native (llama.cpp, LM Studio, Ollama) |
| Kilo Code | Yes | No | No | No | No | Yes |
| OpenHands | Yes | Yes | Yes | No | No | LiteLLM/local |
| Cursor | Subscription | Subscription | Yes | Yes | No | No |
| Roo | Yes | Yes | No | No | No | Yes |

### Endpoint configuration flexibility

| Harness | Custom base URL | Multiple providers | Per-model provider | Failover | Routing |
|---|---:|---:|---:|---:|---:|
| Claude Code | No | No | No | No | No |
| Codex CLI | Yes (Responses only) | Yes | Yes | No | No |
| OpenCode | Yes | Yes | Yes | No | AI SDK routing |
| Goose | Yes | Yes | Yes | No | Provider selection |
| Qwen Code | Yes | Yes (simultaneous) | Yes | No | SDK-based routing |
| Continue | Yes | Yes | Yes | No | Model-level config |
| Pi | Yes | Yes | Yes | No | Adapter-based |
| Zed | Yes | Yes | Yes | No | Per-model wire choice |
| Aider | Yes | Yes (LiteLLM) | Yes | LiteLLM fallback | LiteLLM routing |
| Cline | Yes | Yes | Yes | No | Profile selection |
| Crush | Yes | Yes | Yes | No | Provider autodiscovery |
| Kilo Code | Yes | Yes | Yes | No | OpenCode-derived routing |
| OpenHands | Yes (LiteLLM/ACP) | Yes | Yes | LiteLLM fallback | LiteLLM/ACP routing |
| Cursor | No | No | No | No | Subscription-only |
| Roo | Yes | Yes | Yes | No | Profile selection |

### Telemetry and observability

| Harness | Credits | Quota | Session remaining | Rate limits | Cost estimation | Context remaining | Streaming tokens | Token events | Provider latency | Retries | Billing info |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Claude Code | No (internal) | Yes (CLI display) | Partial (CLI %) | Yes (CLI reset time) | No | Partial (CLI %) | No | No | No | No | No |
| Codex CLI | Yes | Yes | Yes | Yes | Yes | Yes | Yes | Yes | No | No | Dashboard |
| OpenCode | Varies | Varies | Yes | Varies | Varies | Yes | Provider dependent | Provider dependent | No | No | No |
| Goose | Varies | Varies | Yes | Varies | Varies | Yes | Provider dependent | Provider dependent | No | No | No |
| Qwen Code | Varies | Varies | Yes | Varies | No | Yes | Provider dependent | Provider dependent | No | No | No |
| Continue | Varies | Varies | Yes | Varies | No | Yes | Provider dependent | Provider dependent | No | No | No |
| Pi | Varies | Varies | Yes | Varies | No | Yes | Provider dependent | Provider dependent | No | No | No |
| Zed | No | No | No | No | No | Yes | No | No | No | No | No |
| Aider | No | No | Partial | No | LiteLLM | Partial | LiteLLM only | LiteLLM only | No | LiteLLM | No |
| Cline | OpenRouter only | OpenRouter only | Yes (OpenRouter) | OpenRouter only | OpenRouter only | Yes | Yes | Yes | No | No | OpenRouter billing |
| Crush | No | No | Partial | No | No | Partial | No | No | No | No | No |
| Kilo Code | No | No | Partial | No | No | Partial | No | No | No | No | No |
| OpenHands | Varies (ACP) | Varies (ACP) | Yes (ACP) | Varies (ACP) | No | Yes (ACP) | LiteLLM only | LiteLLM only | No | LiteLLM | ACP limited |
| Cursor | No | No | No | No | No | No | No | No | No | No | No |
| Roo | Varies | Varies | Yes | Varies | No | Yes | Provider dependent | Provider dependent | No | No | No |

## Scheduling implications

The telemetry dimension is what matters most for cross-provider scheduling. Here's what each tier can do:

### Tier 1 — Full telemetry (Codex CLI, OpenCode)

These harnesses expose budget, quota, and session data through documented APIs or CLI output. AUDiaGentic can make informed scheduling decisions: check balance before dispatching, defer on rate limits, switch on context exhaustion.

### Tier 2 — Partial telemetry (Goose, Qwen Code, Continue, Cline)

These harnesses expose some telemetry but not all. Scheduling is possible but with gaps — for example, Cline tracks OpenRouter credits and billing, but not Anthropic or OpenAI quotas through the same interface.

### Tier 3 — Local context only (Pi, Zed, Crush, Kilo Code)

These harnesses can report context window state but not budget or rate limits. Scheduling can avoid context overflow but cannot proactively manage spend.

### Tier 4 — No telemetry (Claude Code, Cursor, Aider, OpenHands legacy)

These harnesses expose no budget or quota data. Claude Code is the most important case: it knows about its own subscription usage windows and rate limits (displayed in the CLI), but has no public API to surface that data. AUDiaGentic would need a provider plugin to scrape/observe this telemetry.

## Open questions

- Can Anthropic's internal endpoints be reliably intercepted for Claude Code telemetry? What is the fragility risk?
- Do all OpenRouter-compatible gateways expose the same telemetry endpoints?
- Is there a standard for local model runtime metrics (VRAM, KV cache) across llama.cpp, vLLM, SGLang?
- Should cost estimation use per-model pricing or per-provider pricing when both are available?
- Can Codex's Responses API be used to track per-session token consumption in real time?
