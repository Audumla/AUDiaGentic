# Provider Telemetry Capability Model

Status: authoritative reference candidate  
Last validated: 2026-07-17  
Planning set: `docs/planning/active/ptm-telemetry/PT01..PT02`

This document defines the multi-dimensional provider telemetry model and per-harness capability matrix that replaces the binary `supports_credits` flag. Every provider declares which telemetry categories it can expose, and every harness is evaluated for its ability to monitor, budget, and schedule work across providers.

## Why this matters

The scheduling layer is where real differences between harnesses become apparent. It's not enough to know "can this harness talk to OpenRouter?" — you also need to know "can AUDiaGentic monitor, budget, and intelligently schedule work across providers?"

"Remaining credits" is not standardized. Every provider exposes something different (or nothing at all). The major distinction:

- **Credits** — account-level budget
- **Session usage** — per-session token/credit consumption
- **Context window** — remaining tokens before context overflow
- **Rate limits** — requests per time window

These are four independent axes that affect scheduling decisions.

## Per-harness capability matrix

The important distinction for each harness is whether it can expose telemetry to AUDiaGentic, not just whether it can connect to a provider.

### Harness connectivity table

| Harness | Native vendors | OpenAI-compatible | Custom endpoint | Local models | Per-provider auth | Credits API | Session API | Context API | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Claude Code | Anthropic | No | No | No | Yes | No (internal only) | Yes | Partial | CLI shows "27% remaining" and "2 hours until reset" |
| Codex CLI | OpenAI | No | Yes (Responses only) | Ollama, LM Studio | Yes | Yes | Yes | Yes | Full API + dashboard access |
| OpenCode | Anthropic, OpenAI, Gemini | Yes | Yes | Yes | Yes | Varies | Varies | Yes | AI SDK providers; per-provider auth |
| Goose | Anthropic, OpenAI, Gemini | Yes | Yes | Ollama, LM Studio | Yes | Varies | Varies | Yes | Native and custom providers |
| Qwen Code | OpenAI, Anthropic, Gemini | Yes | Yes | Yes | Yes | Varies | Varies | Yes | `modelProviders` with per-provider SDKs |
| Continue | Anthropic, OpenAI, Gemini | Yes | Yes | Yes | Yes | Varies | Varies | Yes | YAML model entries; roles/capabilities |
| Pi | Anthropic, OpenAI, Gemini | Yes | Yes | Yes | Yes | Varies | Varies | Yes | User JSON provider blocks |
| Zed | OpenAI, Anthropic, Gemini | Yes | Yes | Ollama, LM Studio, llama.cpp | Yes | No | No | Yes | Keychain/env creds; per-model wire choice |
| Aider | OpenAI, Anthropic (LiteLLM) | Yes | Yes | Ollama | Yes | No | No | Partial | Launch env + model flag |
| Cline | OpenRouter, OpenAI | Yes | Yes | Yes | Yes | Yes (OpenRouter) | Yes | Yes | Extension profile; billing tracking |
| Crush | OpenAI, Anthropic (litellm) | Yes | Yes | Ollama, llama.cpp, LM Studio | Yes | No | No | Partial | Native provider types incl. local |
| Kilo Code | OpenAI, Anthropic, Gemini | Yes | Yes | Ollama, LM Studio | Yes | No | No | Partial | OpenCode-derived provider model |
| OpenHands | LiteLLM, ACP agents | Yes (LiteLLM) | Yes | Yes | Yes | Varies | Varies | Yes | Launch env/SDK; ACP auth via subscription or API key |
| Cursor | Subscription | No | No | No | Subscription | No | No | No | No generic endpoint projection |
| Roo | OpenRouter, OpenAI | Yes | Yes | Yes | Yes | Varies | Varies | Yes | Extension profile; manual |

### Provider telemetry table

This captures what each provider actually exposes.

| Provider | Remaining credits | Remaining session usage | Remaining context | Practical access |
|---|---:|---:|---:|---|
| Anthropic (Claude) | Subscription usage windows | Yes | Partial | Internal endpoints/UI only — no public API |
| OpenAI (Codex) | API credits and usage | Responses/session state | Yes | Official API + dashboard |
| OpenRouter | Credits | Request usage | Yes | Official API |
| Gemini | API quota | Request quota | Yes | Official API |
| GitHub Copilot | Subscription only | No | No | Very limited |
| Azure OpenAI | Azure quota | Deployment usage | Yes | Azure APIs |
| Ollama | N/A | Local only | Yes | Local API |
| llama.cpp | N/A | Local only | Yes | Local API |
| vLLM | N/A | Local only | Yes | Local/OpenAI API |
| LM Studio | N/A | Local only | Yes | Local API |
| LiteLLM Proxy | Gateway credits (if enabled) | Varies by backend | Yes | List API + backend passthrough |

## Claude — the awkward one

Anthropic does not expose a public API for budget telemetry. There are three different "budgets":

1. **Subscription usage** — how much of your monthly quota you've consumed
2. **Session context** — tokens remaining in the current session
3. **Rate limiting** — requests per time window before reset

The CLI itself knows these limits because it displays messages like:

```
27% remaining
2 hours until reset
```

There are several possibilities for AUDiaGentic to surface this data:

- Intercept the internal endpoint the CLI already calls
- Parse the WebSocket/event stream
- Parse CLI status events
- Estimate locally (token counting)

AUDiaGentic should support both:

- **Official API** — unavailable for Anthropic subscription telemetry
- **Provider plugin** — scrape/observe via one of the above methods

Claude is too important not to support. This is a `probe-required` capability with a named probe and expected evidence.

## Codex / OpenAI — clean integration

You can obtain through documented APIs:

- Account credits
- API usage
- Billing history
- Model usage per model

The missing piece is **session remaining context**, which must usually be estimated locally because tokenizers differ slightly between providers.

## OpenRouter — best telemetry support

OpenRouter exposes through their API:

- Remaining credits
- Usage history
- Rate limits
- Model availability

This is the ideal provider plugin target — full, documented, queryable.

## Gemini — straightforward

Gemini exposes through Google APIs:

- Quota usage
- Request limits
- Model availability

Again, straightforward integration via documented APIs.

## Local models — different telemetry entirely

There are no credits for local models. The useful values become:

- Remaining VRAM
- Remaining KV cache
- Remaining context window
- GPU utilization
- Queue depth
- Tokens/sec throughput
- Batch utilization

These are actually **more useful** for scheduling than remote provider credits, because they reflect real-time capacity rather than billing state.

## Provider telemetry data model

Rather than `supports_credits = true`, define a structured telemetry declaration:

```yaml
provider:
  telemetry:
    balance:
      supported: true
      source: "official-api" | "scrape" | "estimate"

    quota:
      supported: true

    subscription:
      supported: true

    session:
      remaining_context: true
      remaining_tokens: true
      request_limit: true
      rate_limit: true
      reset_time: true

    runtime:
      gpu_usage: true
      vram_usage: true
      kv_cache: true
      queue_depth: true
      throughput: true

    cost_estimation:
      supported: true
      model_prices_source: "provider-api" | "static-catalog" | "estimate"

    observability:
      streaming_token_counts: true
      token_usage_events: true
      provider_latency: true
      retries: true
      billing_info: true
```

Every provider implements whichever pieces exist. Unknown fields default to `unsupported`, never `true`.

### Source provenance

Telemetry values must carry their source:

- **official-api** — obtained from the provider's documented public API
- **scrape** — obtained by observing internal endpoints, UI state, or CLI events (fragile)
- **estimate** — derived locally (token counting, cost estimation)
- **none** — not available

This affects scheduling reliability: official data is trustworthy; scraped data may break; estimated data may be inaccurate.

## Telemetry query service

The service layer exposes three primary queries:

| Tool | Description | Returns |
|---|---|---|
| `get_provider_balance` | Account-level budget | Credits, subscription remaining, reset time |
| `get_provider_quota` | Rate limits and request budgets | Requests remaining, window, next reset |
| `get_session_telemetry` | Current session state | Remaining context, tokens used, rate limit state |

Each query returns structured data or `None` — never crashes on an unsupported category.

### Telemetry categories by provider

```yaml
# Anthropic (Claude) example
anthropic:
  telemetry:
    balance:
      supported: true
      source: "scrape"
    subscription:
      supported: true
    session:
      remaining_context: true       # partial — CLI shows percentage
      rate_limit: true             # CLI shows reset time
    observability:
      streaming_token_counts: false  # no official API

# OpenAI example
openai:
  telemetry:
    balance:
      supported: true
      source: "official-api"
    quota:
      supported: true
    session:
      remaining_context: true
      remaining_tokens: true
    cost_estimation:
      supported: true
      model_prices_source: "provider-api"
    observability:
      streaming_token_counts: true
      token_usage_events: true

# Ollama example
ollama:
  telemetry:
    runtime:
      gpu_usage: true
      vram_usage: true
      kv_cache: true
      queue_depth: true
      throughput: true
    session:
      remaining_context: true
```

## Scheduling integration spec

Telemetry feeds into the scheduling layer with these rules:

1. **Balance check** — before dispatching to a provider, verify sufficient credits/budget remain
2. **Rate limit awareness** — if a provider is approaching its rate limit, defer or route elsewhere
3. **Context window estimation** — track per-session token consumption; switch providers or sessions when context is exhausted
4. **Runtime capacity** — for local models, check VRAM/KV cache before dispatching heavy workloads
5. **Cost estimation** — compare estimated cost across available providers for a given model/task

The scheduler does not make assumptions about which telemetry categories a provider exposes. It queries the service layer, gets structured data or `None`, and makes best-effort decisions.

### Scheduling decision flow

```
request arrives
  → select candidate providers (by model, by capability)
  → query balance for each candidate
  → filter out providers with insufficient budget
  → query quota for remaining candidates
  → filter out providers at rate limit
  → estimate cost for remaining candidates
  → select lowest-cost or best-fitting provider
  → dispatch with telemetry tracking
```

## Validation language

Every telemetry capability must carry one of these effective states:

| State | Meaning |
|---|---|
| `official-api` | Obtained from the provider's documented public API |
| `scrape` | Obtained by observing internal endpoints, UI state, or CLI events |
| `estimate` | Derived locally (token counting, cost estimation) |
| `none` | Not available — returns `None` |

Do not use placeholders. An unknown telemetry field is `none`, with a named reason if applicable.

## Relationship to provider model endpoint capabilities

This document complements `../endpoints/provider-model-endpoints.md`. That document covers **how** AUDiaGentic projects model sources into agent config files. This document covers **what** telemetry each provider exposes and **whether** each harness can surface that telemetry for scheduling decisions.

Together, these two documents answer the core question: "Can AUDiaGentic monitor, budget, and intelligently schedule work across providers?"

## Open questions

- Can Anthropic's internal endpoints be reliably intercepted? What is the fragility risk?
- Do all OpenRouter-compatible gateways expose the same telemetry endpoints?
- Is there a standard for local model runtime metrics (VRAM, KV cache) across llama.cpp, vLLM, SGLang?
- Should cost estimation use per-model pricing or per-provider pricing when both are available?
