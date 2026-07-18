# Provider Model Endpoint Capabilities

Status: authoritative reference candidate  
Last validated: 2026-07-16  
Planning set: `docs/planning/active/model-endpoint-management/MO01..MO10`

This document defines how AUDiaGentic declares, validates, projects, observes, and removes model access across third-party coding agents and editor agents. It covers local inference servers, self-hosted gateways, direct vendor APIs, hosted model aggregators, and native account/subscription paths.

The source document mixed three different questions:

1. **What model source has the user enabled?**
2. **Which wire protocols and capabilities does that source actually implement?**
3. **How can each agent consume that source without corrupting user-owned configuration?**

Those are separate axes in this revision. A product name such as Ollama, OpenRouter, or Anthropic is not itself a projection mechanism, and “OpenAI-compatible” is not a sufficient capability statement for an agent loop.

> **Local endpoints are not a new vendor.** Ollama, LM Studio, llama.cpp, vLLM all use the openai-compatible connector. They do not get their own vendor category, capability fact, or data model — they're the same wire format as OpenAI, just with a different base URL and no key (usually). Provider-specific projection mechanics (Codex's --oss --local-provider, Qwen's --openai-base-url, OpenHands' LLM_BASE_URL) are how that connector is expressed, not a new taxonomy.


## Validation language

Every provider/source fact must carry one of these effective states in implementation and review notes:

| State | Meaning | May auto-write? |
|---|---|---:|
| `repo-verified` | Confirmed against the current AUDiaGentic repository. | Yes, subject to tests. |
| `upstream-verified` | Confirmed against current upstream documentation or schema. | Only after installed-version and path probes pass. |
| `runtime-verified` | Confirmed against the installed executable/version in the target environment. | Yes. |
| `probe-required` | Upstream support exists, but the installed version, scope, merge behavior, or reload behavior has not been confirmed. | No. |
| `manual` | Capability exists but no safe, stable, non-secret persistent automation surface is available. | No. |
| `unsupported` | The consumer cannot use that source/protocol. | No. |

Do not use placeholders as defaults. An unknown field is a blocker represented as `probe-required`, with a named probe and expected evidence.

## Goal

Declare model access once in AUDiaGentic project config, then let the `providers` component project that desired state into each compatible agent’s native configuration while:

- preserving unmanaged user entries;
- never persisting resolved secret values in AUDiaGentic registries, status, logs, or timelines;
- making project-scope writes the default;
- requiring explicit consent for user-home, editor-global, keychain, or account mutations;
- qualifying protocol and agent-loop behavior before declaring an endpoint usable;
- removing only entries AUDiaGentic owns; and
- reporting the difference between **declared**, **materialized**, **discoverable**, and **runtime-usable** models.

This remains the same problem shape as managed MCP and language-server projection: one desired state, multiple provider-specific config surfaces, and reversible ownership. Model projection is a **managed-config kind**, not a parallel subsystem.

## Non-negotiable design position

- `agents` own profile selection and bind `provider_id` + `model_id` at dispatch time.
- `providers` own model-source compatibility, provider config rendering, auth references, model catalogs, protocol qualification, refresh/reload behavior, and provider status.
- Recipes call provider-owned sync/status operations; recipes never hand-edit provider config files.
- Structured adapters use parse/merge/render operations, never text patching.
- Unmanaged provider/model entries survive every reconcile.
- Env/argument projection is not forced through fragment reconciliation.
- Editor extension storage is not written by guessing paths or internal storage formats.
- User-global writes require consent and dry-run support.
- Native subscriptions and OAuth account catalogs are not represented as arbitrary endpoint entries unless the consumer exposes a supported gateway/base-URL contract.

## Current code facts this plan must respect

The repository already has useful primitives, but the model-config consolidation is not complete.

| Area | Current repository state | Required planning consequence |
|---|---|---|
| Provider config specs | `McpConfigSpec` and `LanguageServersConfigSpec` remain separate dataclasses in `components/providers/descriptors/base.py`. MCP has `refresh_mode`, `reload_fn`, and `remote`; LSP does not. | Extract a common `ManagedConfigSpec` with optional kind-specific fields. Do not claim it already exists. |
| Descriptor loading | `loader.py` has `_build_mcp_config` and `_build_language_servers_config`. | Replace with one managed-config builder/map while retaining descriptor YAML compatibility. |
| Reconciler | `foundation/toolchains/fragments.py` is domain-opaque: `FragmentStore`, `reconcile_fragments`, opaque `owner_scope`, and `Any` payloads. | Reuse it for structured model entries. Do not add another reconciler. |
| Registry | `managed_mcp_registry.py` is hard-coded to `.audiagentic/runtime/providers/managed-mcp-servers.json`. | Generalize it into parameterized `ManagedFragmentRegistry` instances. |
| MCP service | `services/mcp.py` already resolves a config path, binds a store, reconciles fragments, and reloads/reports no-op. | Extract `sync_managed_config` and `reload_managed_config`; keep MCP/LSP/model wrappers thin. |
| Recipe framework | `ProviderRecipeKind` has no model-config kind. `NoAutomationRecipe` returns guidance only. | Add an explicit model-config kind plus a separate launch-env contribution recipe. |
| OpenCode | Harness writes `.opencode/config.json` with top-level `providers`; descriptor manages `.opencode/opencode.json`. Current upstream uses `opencode.json`/`opencode.jsonc` and top-level `provider` singular. | Treat this as a schema-and-location migration gate for MCP, LSP, and models together. Neither current repository shape should be assumed current upstream. |
| Goose | Repository descriptor uses project `.goose/config.yaml`; execution is a stub. Current upstream uses a user config under the platform config directory, supports custom providers, and supports launch-time provider/model overrides. | Keep execution blocked until bridged. Prefer launch env first; persistent Goose writes require a validated project override or consented user-config adapter. |
| Codex | Descriptor manages project `.codex/config.toml` for MCP/LSP. | Project `model_providers` is preferred and is now upstream-supported for trusted projects; user-global config is fallback only. Qualify the Responses API before enabling. |
| OpenHands | Descriptor manages `.openhands/config.toml`. Current OpenHands has restructured: Agent Canvas is the new developer control center running multiple agents (OpenHands, Claude Code, Codex, Gemini CLI) via ACP. V1 UI/env/SDK flows; legacy V0 TOML config deprecated. ACP agents authenticate via subscription login or API key. LLM profiles (up to 10 per account) allow mid-conversation switching. | Make the adapter version-aware. Do not write an `[llm]` table unless the runtime is confirmed V0-compatible. ACP agent support may enable agent-level model selection without config mutation. |
| Continue | Descriptor manages `.continue/config.json`. Current upstream marks JSON deprecated and prefers `config.yaml`, which also carries MCP. | For current Continue, migrate MCP + models atomically to YAML. Retain JSON only for explicitly pinned legacy versions. |
| Qwen Code | No model writer is implemented. Current upstream supports user and project `.qwen/settings.json` plus `modelProviders` with per-provider SDKs (openai, @anthropic-ai/sdk, @google/genai). Model uniqueness by id+baseUrl; per-model generationConfig with timeout, maxRetries, contextWindowSize, customHeaders, extra_body, samplingParams. `/model` switching supports multi-provider. | Promote Qwen to a structured P1 candidate after merge/collision/reload tests. Multi-provider simultaneous support is confirmed. |
| Pi | Harness template `home/agent/models.json` is home-scoped and has a verified `providers.<id>.models[]` shape. | Treat writes as consented user-home writes unless a project override is runtime-verified. |
| Execution stubs | `aider`, `openhands`, `goose`, and `plandex` execution bridges are stubs; Roo is unsupported. | Env/argument projections remain inert and must report blocked until execution exists. |
| `local-openai` | Catalog emits invalid schema values (`available`, `None` context window). | Fix this first and add schema tests before broad projection. |
| New candidates | Crush, Kilo Code, and Zed do not yet have provider descriptors. | Add descriptors only after the shared model-config contract lands; do not bypass it with special-case writers. |

## Source model: preserve v1 wire names, correct the semantics

The implemented v1 schema uses `local-endpoint` and `remote-account`. Those names are location/auth-oriented and become misleading for a self-hosted multi-model gateway or a keyed single-model remote endpoint.

For v1 compatibility, retain the serialized values, but interpret them by behavior:

| v1 serialized class | Semantic name | Contract | Can be physically local or remote? |
|---|---|---|---:|
| `local-endpoint` | **declared model** | Exactly one endpoint + model declaration. No discovery is required. | Yes. |
| `remote-account` | **catalog source** | One connection may expose zero or more models via discovery or a curated catalog. Auth is optional. | Yes. |

This means:

- a local llama.cpp server exposing one model is `local-endpoint`;
- a remote dedicated endpoint exposing one model may also use `local-endpoint`;
- a self-hosted LiteLLM, LlamaSwap, LocalAI, SGLang, TGI, vLLM, or Ollama gateway exposing several models uses the **catalog-source behavior**, even though v1 serializes it as `remote-account`;
- a vendor account with one selected deployment can still use the declared-model behavior when discovery is undesirable.

A v2 schema may rename these values to `declared-model` and `catalog-source`. Do not add a third class merely to compensate for the v1 names.

### Discovery is independent of projection

`model-discovery` describes what AUDiaGentic knows about a catalog source:

- `static-catalog` — curated records under `src/audiagentic/config/providers/model-catalogs/<source-id>.yaml`;
- `list-api` — fetched from a source catalog endpoint such as `/v1/models`; and
- `none` — connectivity can be projected, but AUDiaGentic has no source-side model list.

Catalog refresh is best-effort:

1. use a fresh result when available;
2. otherwise retain the last valid cache;
3. emit warning + `action_needed` with the classified failure;
4. never fail unrelated config reconciliation solely because discovery is temporarily unavailable.

Discovery records must include provenance and freshness:

```yaml
catalog-state:
  source: list-api
  fetched-at: 2026-07-16T00:00:00Z
  expires-at: 2026-07-17T00:00:00Z
  etag: optional
  stale: false
  last-error: null
```

### Projection modes

Projection is selected from declared provider capabilities, never by product-name branching:

1. `native-account` — the agent owns login/account discovery. AUDiaGentic may select a model but does not inject credentials or materialize vendor models.
2. `native-key-env` — the agent natively supports the source and reads a documented ambient variable.
3. `native-key-config` — the agent supports a documented config field or env-reference field.
4. `custom-entries` — AUDiaGentic materializes explicit provider/model entries from the source declaration/catalog.
5. `launch-env` — AUDiaGentic contributes variables and arguments only when launching the agent.
6. `manual` — user action is required through a UI, keychain, OAuth flow, or unstable extension storage.
7. `none` — incompatible.

The selected mode is a fact of `(agent provider, model source, installed version)`, not merely `(agent provider, connector)`.

### Standalone rule

Agents normally run independently of AUDiaGentic. Therefore:

- an ambient env-based integration is enabled only when the required variable is already present in the user environment;
- AUDiaGentic may verify `has_ambient_value`, but does not mutate shell profiles or OS environment variables;
- launch-env support is reported as **AG-launched sessions only**, never as generally enabled; and
- config entries should reference environment variables where the target supports it, rather than embedding resolved keys.

### Materialization and ownership

A source produces desired entries for the shared reconcile machinery:

- declared model: `model-endpoints/<source-id>`;
- catalog-derived model: `model-endpoints/<source-id>/<model-id>`;
- connection-only config: `model-connections/<source-id>`.

Use `owner_scope = <agent-provider-id>`. Provider-visible names may change; managed IDs must remain stable.

`model-filter` applies to:

- catalog-source aliases exposed by AUDiaGentic; and
- `custom-entries` materialization.

It does not constrain a native account/key path where the consumer discovers the vendor’s complete catalog itself. Status must say this explicitly.

## Protocol and capability model

### “OpenAI-compatible” is not one capability

The source keeps a broad connector family, but must also declare/probe specific wire APIs:

```yaml
connector: openai-compatible
wire-apis:
  - chat-completions
  - responses
```

Provider compatibility is the intersection of:

- connector family;
- supported wire API;
- authentication/header mechanism;
- streaming behavior;
- role/message compatibility;
- tool-call request and tool-result continuation behavior; and
- model capabilities required by the agent.

A server that implements `/v1/chat/completions` but not `/v1/responses` is not usable by current Codex. A server that accepts a basic Responses request but mishandles tool-result items is also not Codex-compatible.

### Connector taxonomy

| Connector | Actual protocol | Typical sources | Notes |
|---|---|---|---|
| `openai-compatible` | OpenAI Chat Completions and/or Responses | llama.cpp, vLLM, SGLang, TGI, LocalAI, LM Studio, Ollama shim, LiteLLM Proxy, OpenRouter, many hosted services | Always pair with `wire-apis`; do not infer Responses from Chat Completions. |
| `anthropic` | Anthropic Messages API | Anthropic, compatible gateways | Native headers/versioning; separate from OpenAI shims. |
| `gemini` | Google Generative Language / Gemini API | Gemini API, compatible gateways | Native request/stream/tool schema. |
| `ollama` | Native Ollama API | Ollama | Use only when the consumer has a real native adapter; otherwise use its OpenAI shim. |
| `openrouter` | OpenAI wire plus OpenRouter catalog/routing conventions | OpenRouter | First-class source profile because model IDs, routing, and metadata differ, even though the wire is OpenAI-like. |

The following are **not connectors**:

- `litellm` — a client routing abstraction or proxy product; its proxy surface is usually OpenAI-compatible;
- `native-vendor` — a projection/account mode;
- `frontier vendor`, `aggregator`, `gateway`, and `cloud platform` — descriptive source groupings.

`connector-options` remains a free-form map in v1, but it must not contain inline secret values. Add a typed `header-refs`/secret-reference mechanism before supporting gateways requiring secret custom headers.

### Endpoint qualification probe

Before an endpoint is marked runtime-usable for an agent, run the smallest safe probe set required by that agent. Cache results by endpoint fingerprint + model + provider adapter version.

| Probe | What it establishes |
|---|---|
| Catalog | `/models` works when discovery is configured; model ID is present. |
| Basic generation | Endpoint, auth, streaming, and model ID work. |
| Context metadata | Positive context and output limits are available or explicitly overridden. |
| Roles | Required `system`/`developer` roles are accepted or correctly transformed. |
| Tool declaration | Model accepts the agent’s tool schema. |
| Tool call | Model emits parseable tool calls with stable IDs and valid JSON arguments. |
| Tool continuation | Tool results can be returned and generation continues correctly. |
| Parallel tools | Required only where the agent/provider enables parallel calls. |
| Responses state | Required for Codex and any Responses-stateful adapter. |
| Reasoning fields | Required where reasoning summaries/effort are enabled. |
| Vision | Required only for profiles that declare image input. |

A successful text completion is insufficient evidence for agent compatibility.

Recommended status fields:

```yaml
qualification:
  state: passed|partial|failed|not-run
  provider-id: codex
  model-id: gpt-oss-20b
  endpoint-fingerprint: sha256:...
  checked-at: 2026-07-16T00:00:00Z
  wire-api: responses
  probes:
    basic-generation: passed
    tool-call: passed
    tool-continuation: failed
  action-needed: "Upgrade llama.cpp; Responses tool-result continuation failed"
```

## Upstream service to source mapping

This table lists model sources consumed by agents. It does not list the agent providers themselves.

| Upstream service/product | Semantic source behavior | Grouping | Connector/wire | Discovery | Priority | Position |
|---|---|---|---|---|---:|---|
| llama.cpp / vLLM / SGLang / TGI / LocalAI / LM Studio | Declared model or catalog source | local/self-hosted serving | OpenAI-compatible; Chat and/or Responses varies by server/version | declared or list API | P1 | Core local path; qualify per wire API and tool loop. |
| LlamaSwap or similar model router | Catalog source | self-hosted gateway | Pass-through OpenAI-compatible; capabilities vary by selected backend | list API if exposed | P1 | Treat as gateway, not a model runtime. Endpoint fingerprint must include routed model. |
| Ollama | Declared model or catalog source | local/self-hosted serving | Native Ollama and OpenAI shim | list API/native list | P1 | Prefer native only for consumers with a verified native adapter. |
| LiteLLM Proxy | Catalog source | gateway, local or remote | OpenAI-compatible; optional Responses support depends on deployment/version | list API | P1 | `litellm` is not a wire connector. |
| OpenAI API | Catalog source | frontier vendor | OpenAI native | list API | P1 | Distinct from ChatGPT/Codex subscription login. |
| Anthropic API | Catalog source | frontier vendor | Anthropic Messages | list API | P1 | Anthropic now exposes a Models API; do not default to static-only. |
| Google Gemini API | Catalog source | frontier vendor | Gemini native and optional OpenAI-compatible surface | list API | P1 | Prefer native connector where supported. |
| OpenRouter | Catalog source | model gateway/aggregator | OpenRouter/OpenAI-compatible | list API | P1 | Filter custom materialization aggressively. |
| OpenCode Zen / OpenCode Go | Catalog source | curated gateway/service | OpenCode provider API | provider catalog | P2 | Native to OpenCode; other consumers may use OpenCode API support where documented. |
| Alibaba Model Studio / DashScope | Catalog source | vendor platform | OpenAI-compatible and vendor-native variants | probe/list API | P2 | Distinct from Qwen Code, the consumer. |
| xAI | Catalog source | frontier vendor | OpenAI-compatible | list API | P2 | Verify tool and Responses behavior per model. |
| Mistral | Catalog source | frontier vendor | Mistral native/OpenAI-like client surfaces | list API | P2 | Prefer native consumer adapter when present. |
| DeepSeek | Catalog source | frontier vendor | OpenAI-compatible | list API | P2 | Verify reasoning-content compatibility. |
| Groq, Together, Fireworks, Cerebras, SambaNova, Nebius, SiliconFlow, Novita | Catalog source | hosted open-model inference | Usually OpenAI-compatible | probe/list API | P2 | Add source descriptors individually; do not collapse auth/catalog quirks into one runtime ID. |
| Moonshot/Kimi, Z.ai/GLM, MiniMax | Catalog source | model vendor/platform | Often OpenAI-compatible plus vendor extensions | probe/list API | P2 | Worth supporting where coding agents already expose native/provider entries. |
| Vercel AI Gateway, Tetrate Agent Router, Requesty | Catalog source | gateway | OpenAI-compatible and/or multi-protocol | probe/list API | P2 | Gateway headers/routing options belong in connector options with secret refs. |
| Docker Model Runner / Ramalama | Declared model or catalog source | local serving | Consumer-specific native support or OpenAI-compatible | probe | P2 | Add only where an agent has a verified adapter. |
| Azure OpenAI | Catalog/deployment source | cloud platform | Azure OpenAI | deployment API | P3 | Deployment names, API versions, and Entra/key auth need a dedicated profile. |
| AWS Bedrock / SageMaker | Catalog/deployment source | cloud platform | Bedrock/Converse or hosted endpoint | cloud API | P3 | IAM/profile/region semantics exceed the generic API-key shape. |
| GCP Vertex AI | Catalog/deployment source | cloud platform | Vertex Gemini/partner models | cloud API | P3 | OAuth/project/location semantics need a dedicated profile. |

Do not add every OpenAI-compatible vendor as a new connector. Add a source descriptor/catalog and reuse the connector family plus explicit wire/capability facts.

## Relationship to profiles, aliases, and runtime availability

- Agent profiles bind `provider_id` + `model_id`; they do not bind source IDs or URLs.
- Aliases resolve against models produced by enabled sources and usable by the selected provider.
- Disabling a source invalidates affected aliases with an explicit validation error; no silent fallback.
- Source mutations occur only in `.audiagentic/config/model-sources.yaml` or through tools that validate and update that file.
- Provider config files are projection targets, never the desired-state mutation surface.

### Declared, materialized, discoverable, qualified, selected

These states are deliberately different:

1. **Declared** — source exists and is enabled in AUDiaGentic.
2. **Materialized** — owned entry/env contribution was successfully projected.
3. **Discoverable** — provider runtime catalog lists the model.
4. **Qualified** — required protocol/tool-loop probes passed.
5. **Selected** — a profile/default points to the model.

Where a provider exposes `fetch_catalog_fn`, its refreshed runtime catalog is authoritative for current discoverability. A managed entry missing from the next catalog read is a reconcile discrepancy, not success.

Provider model validation should require:

```text
enabled source
AND compatible projection
AND materialized/native availability
AND runtime discoverability when available
AND qualification passed for the profile’s required capabilities
```

## Managed mechanisms

| Mechanism | Primary targets | Managed unit | Ownership | Implementation |
|---|---|---|---|---|
| Project structured config | OpenCode, Kilo, Qwen project settings, Crush project config, Codex project config, Continue project config where supported | Provider block/model entry/default pointer | Fragment registry | `ManagedConfigSpec` + shared reconcile core |
| Consented user structured config | Pi, Qwen user settings, Goose user config, Zed settings, Codex fallback, Crush/Kilo global fallback | Provider block/model entry | Fragment registry plus consent record | Same core with scope policy |
| Native AUDiaGentic catalog | `local-openai` | Catalog entry/alias | AG-owned catalog | Schema-valid catalog bridge |
| Launch env/args | OpenHands, Aider, Goose, any execution-bridged CLI | Env vars and arguments | No persistent fragment | Launch contribution recipe |
| Keychain/OAuth/manual | Zed credentials, OpenCode `/connect`, native subscriptions, extension provider UIs | Account credential/profile | User/tool owned | Guidance/status only unless a first-class host API exists |
| Extension storage/manual | Cline and Roo | Extension profiles | User/tool owned | No automation until stable public config surface exists |
| Cloud identity profile | Bedrock, Vertex, Azure | Cloud profile/deployment | User/cloud owned | Dedicated future adapters, not generic key injection |

## Proposed managed source shape

Canonical file: `<project-root>/.audiagentic/config/model-sources.yaml`.

The v1 source classes remain for compatibility, but the example adds explicit wire capabilities and qualification policy.

```yaml
contract-version: v1
sources:
  qwen-local:
    source-class: local-endpoint       # semantic behavior: declared model
    display-name: Qwen local
    connector: openai-compatible
    base-url: http://127.0.0.1:1234/v1
    api-key-ref: env:AUDIAGENTIC_LOCAL_API_KEY
    model-id: qwen3-coder
    wire-apis:
      - chat-completions
      - responses
    context-window: 262144
    max-output-tokens: 16384
    capabilities:
      tool-use: true
      parallel-tools: false
      reasoning: false
      vision: false
      developer-role: false
    qualification-policy:
      require:
        - basic-generation
        - tool-call
        - tool-continuation
    provider-overrides:
      pi:
        api: openai-completions
        compat:
          supportsDeveloperRole: false
          supportsReasoningEffort: false
      codex:
        require-wire-api: responses
      zed:
        chat-completions: true

  local-gateway:
    source-class: remote-account       # v1 wire name; semantic behavior: catalog source
    display-name: Local LiteLLM gateway
    connector: openai-compatible
    base-url: http://127.0.0.1:4000/v1
    api-key-ref: env:LOCAL_GATEWAY_API_KEY
    wire-apis: [chat-completions, responses]
    model-discovery: list-api
    model-filter:
      include: ["qwen/*", "openai/gpt-oss-*"]
    enabled: true

  anthropic-account:
    source-class: remote-account
    display-name: Anthropic API
    vendor-id: anthropic
    connector: anthropic
    api-key-ref: env:ANTHROPIC_API_KEY
    model-discovery: list-api
    enabled: true

  openrouter-main:
    source-class: remote-account
    display-name: OpenRouter
    vendor-id: openrouter
    connector: openrouter
    base-url: https://openrouter.ai/api/v1
    api-key-ref: env:OPENROUTER_API_KEY
    model-discovery: list-api
    wire-apis: [chat-completions]
    model-filter:
      include: ["anthropic/*", "qwen/*", "openai/gpt-oss-*"]
      exclude: ["*-preview"]
    enabled: true
```

### Required schema follow-ups

The implemented v1 schema should be extended, compatibly where possible, with:

- `wire-apis`;
- `qualification-policy`;
- `header-refs` or an equivalent secret-reference map;
- discovery cache policy/TTL;
- explicit endpoint TLS policy only if required for private PKI;
- provider override validation keyed by descriptor schema, not arbitrary silent keys.

No resolved secret value may be serialized into this file.

### Ownership and collision rules

- Keep stable managed IDs independent of provider-visible names.
- Updating URL/model/capability fields updates only the owned entry.
- Removing a source removes only that source’s owned entries.
- If an unmanaged entry occupies the same provider-visible key, report a collision and do not overwrite it by default.
- `force` must not mean “overwrite anything”; it may replace only a previously owned fragment with a matching ownership record.
- Default/active-model pointers are separately owned fragments and must be restored or removed safely when a source is disabled.

## Provider support modes

Use these status values consistently:

| Mode | Meaning |
|---|---|
| `auto-project` | Safe structured project-scope write and reload are runtime-verified. |
| `auto-user-consent` | Safe user/global structured write exists and user consent is recorded. |
| `launch-only` | Works only when AUDiaGentic launches the provider with env/args. |
| `native-account` | Tool owns login and catalog; AUDiaGentic may only validate/select. |
| `manual` | User UI/keychain/storage action required. |
| `blocked` | Upstream may support it, but repository execution/schema/scope/reload validation is incomplete. |
| `unsupported` | No compatible path. |

## Agent-provider capability matrix

| Agent provider | Custom/local endpoint | Current upstream surface | Scope | Wire/protocol constraints | Recommended status | Priority |
|---|---:|---|---|---|---|---:|
| `local-openai` | Yes | Native AG catalog | Project/runtime | OpenAI-compatible bridge | `auto-project` after catalog fix | P1 |
| `opencode` | Yes | `opencode.json`/`opencode.jsonc`; top-level `provider`, `model`, `small_model` | Project + global | AI SDK providers; local/OpenAI-compatible supported | `blocked` until repository migration, then `auto-project` | P1 |
| `pi` | Yes | `~/.pi/agent/models.json` provider blocks | User home | Adapter-specific `api`/`compat` metadata | `auto-user-consent` after reload/default probe | P1 |
| `codex` | Yes, constrained | `.codex/config.toml` or `~/.codex/config.toml`; `[model_providers.<id>]`; profiles via `~/.codex/<name>.config.toml`; auth commands, HTTP headers, model catalog | Project + user; **note**: project-local cannot override `model_providers`, so custom providers require user-level config | Responses API only for custom providers; built-in Amazon Bedrock provider; Azure provider with query_params/retries | `auto-project` after qualification (user fallback consented); custom providers must be in `~/.codex/config.toml` due to project-block | P1 |
| `qwen` | Yes | `.qwen/settings.json` or `~/.qwen/settings.json`; `modelProviders` with per-provider SDKs; model uniqueness by id+baseUrl; per-model generationConfig | Project + user | OpenAI, Anthropic, Gemini protocols; multi-provider simultaneous; per-model timeout, maxRetries, customHeaders, extra_body, samplingParams | `auto-project` after merge/reload tests | P1 |
| `crush` | Yes | JSON config with `providers`; local provider types and model autodiscovery | Project + global, validate exact precedence | OpenAI-like/local adapters; explicit provider types | New `auto-project` candidate | P1 |
| `kilo` | Yes | `kilo.jsonc`; shared CLI/editor provider config | Project + global | OpenCode-derived provider model; OpenAI-compatible model discovery | New `auto-project` candidate | P1 |
| `goose` | Yes | User YAML/custom-provider files and launch env overrides | User + launch | Many native providers and OpenAI-compatible paths | `launch-only` first; persistent adapter consented after scope tests | P1/P2 |
| `continue` | Yes | Current `config.yaml`; JSON deprecated | User/project depending installed product path | OpenAI-compatible, native providers, role-specific models | `blocked` pending atomic JSON→YAML migration | P1/P2 |
| `openhands` | Yes | Agent Canvas V1 UI/env/SDK; ACP agents (Claude Code, Codex, Gemini CLI); legacy V0 TOML | Launch/runtime; legacy user/project varies | LiteLLM-style model naming; version-dependent config; ACP auth via subscription login or API key | `launch-only` after execution bridge; TOML only for V0 | P2 |
| `zed` | Yes | `settings.json` `language_models.*`; secrets in keychain/env; custom headers per provider | Editor-global | OpenAI Chat or Responses **per-model**; Anthropic-compatible; native local providers (llama.cpp, Ollama, LM Studio with autodiscovery); reasoning_effort; capabilities model per model | New `auto-user-consent` model-entry candidate; credentials keychain/env only — never in settings.json | P2 |
| `aider` | Yes | CLI/env/`.aider.conf.yml` confirmed; GitHub Copilot now a connecting-to-LLMs provider; reasoning models support | Launch + user/project config | OpenAI-compatible via base URL; LiteLLM model naming; secondary reasoning models | `launch-only` after execution bridge | P2 |
| `cline` | Yes | Three provider paths: Cline usage-billing (OAuth), ClinePass ($9.99/mo), BYOK; IDE settings UI or CLI auth; OpenRouter now named provider id | Extension storage/UI + IDE settings | Broad provider support; OpenRouter named provider | `manual` (BYOK via CLI auth); Cline/ClinePass via OAuth | P2 |
| `roo` | Yes | VS Code extension provider profile | Extension storage/UI | Broad provider support | `manual`; fix descriptor semantics first | P2 |
| `plandex` | Yes, likely | Custom model/provider configuration | Probe required | OpenAI-compatible custom-provider path | `blocked` | P3 |
| `claude` | Gateway/native only | Anthropic login/key and supported enterprise backends | User/account | Not a generic OpenAI-compatible consumer | `native-account` / dedicated gateway recipe | P3 |
| `gemini` | Native vendor | Google login/API configuration | User/account | Native Gemini | `native-account` | P3 |
| `cursor` | Subscription/provider-specific | Cursor account and supported model configuration | User/account | No stable generic project endpoint projection contract assumed | `manual`/`native-account` | P3 |
| `copilot` | No generic endpoint; MCP support for extending capabilities | GitHub account catalog + MCP servers | Account | Account-derived | `native-account`; no generic projection; MCP extends capabilities not model access | N/A |
| `antigravity` | Not an endpoint consumer | Managed-agent API research | Remote | Out of scope | `unsupported` for this feature | N/A |

### Protocol compatibility matrix

`Yes` means upstream capability exists; automation still requires installed-version and repo-adapter validation.

| Provider | OpenAI Chat | OpenAI Responses | Anthropic Messages | Gemini native | Ollama/native local | Main projection path |
|---|---:|---:|---:|---:|---:|---|
| OpenCode | Yes | Provider/model dependent | Yes through native AI SDK provider | Yes through native provider | Yes/local models | Structured project provider block. |
| Pi | Yes | Validate adapter | Via supported adapter/provider | Via supported adapter/provider | Via shim/custom provider | User JSON provider block. |
| Codex | No custom Chat path | **Required** | Only through a gateway exposing Responses | Only through a gateway exposing Responses | Built-in Ollama/LM Studio; custom Responses | Project TOML provider table. |
| Qwen Code | Yes | Probe required | Yes | Yes | Via OpenAI-compatible or configured provider | Project/user `modelProviders`. |
| Crush | Yes/local adapters | Probe required | Provider dependent | Provider dependent | Native provider types include local servers | Project/global JSON provider block. |
| Kilo | Yes | OpenCode-derived/provider dependent | Yes/native provider support | Yes/native provider support | Ollama, LM Studio, custom OpenAI-compatible | Project/global JSONC provider block. |
| Goose | Yes | Provider dependent | Yes | Yes | Ollama, LM Studio, other local providers | Launch env first; user YAML/custom provider later. |
| Continue | Yes | Uses Responses for applicable OpenAI models; can disable | Yes | Yes | Yes | Current YAML `models[]`. |
| OpenHands | Via LiteLLM/OpenAI + ACP agents (Claude Code, Codex, Gemini) | Backend/version dependent | Via LiteLLM or ACP | Via LiteLLM or ACP | Via LiteLLM/OpenAI-compatible or ACP | Launch env/SDK; ACP auth via subscription login or API key. |
| Zed | Yes | Yes per-model via `chat_completions = false` | Yes, including compatible endpoints | Yes (first-class) | Ollama, LM Studio, llama.cpp with autodiscovery; local OpenAI-compatible | User settings model entries + keychain/env secret + custom headers. |
| Aider | Yes | Backend/client dependent | Via LiteLLM | Via LiteLLM | Ollama/OpenAI-compatible | Launch env + model flag. |
| Cline/Roo | Yes | Product/profile dependent | Yes | Yes | Yes | Manual extension profile. |
| Crush | Yes/local adapters | Probe required | Provider dependent (via litellm/gateway) | Provider dependent (via litellm/gateway) | Native provider types: llamacpp, lmstudio, litellm, ollama | Project/global JSON provider block. |
| Kilo Code | Yes | OpenCode-derived/provider dependent | Yes/native provider support | Yes/native provider support | Ollama, LM Studio, custom OpenAI-compatible; auto-fetch from /v1/models | Project/global JSONC provider block with comment preservation. |

### Vendor/account projection matrix

This matrix concerns native vendor/account enablement, not custom endpoints.

| Provider | OpenAI | Anthropic | Google | OpenRouter | Credential ownership | Granularity |
|---|---|---|---|---|---|---|
| Pi | Native env/API key | Native env/API key | Native env/API key | Native env/API key | Ambient env or tool config | Vendor catalog or explicit custom models. |
| OpenCode | `/connect`/provider auth | `/connect`/provider auth | `/connect`/provider auth | Provider supported through OpenCode provider ecosystem/custom config | OpenCode auth store | Vendor catalog; filters via provider config where supported. |
| Codex | Native ChatGPT/API path | Responses-compatible gateway only | Responses-compatible gateway only | Custom Responses provider | Codex config env ref/account | Explicit selected model/provider. |
| Qwen Code | `modelProviders`/auth type + SDK (openai) | `modelProviders`/auth type + SDK (@anthropic-ai/sdk) | `modelProviders`/auth type + SDK (@google/genai) | Custom OpenAI-compatible provider via openai SDK | Env refs from process.env[envKey] — never persisted in settings | Multiple providers simultaneously; model uniqueness by id+baseUrl; per-model generationConfig with timeout, maxRetries, contextWindowSize, customHeaders, extra_body, samplingParams. |
| Goose | Native provider | Native provider | Native provider | Native provider | Goose secret/config system or launch env | One active provider/model; provider catalog available. |
| Continue | Native model entry | Native model entry | Native model entry | Native model entry | Config secret ref/env | Explicit models, roles, and capabilities. |
| Zed | Native API/subscription paths | Native API/subscription paths | Native API path | Native gateway path | Keychain or env | Explicit available models/default model. |
| Aider | Native/LiteLLM | Native/LiteLLM | LiteLLM | LiteLLM | Ambient env/CLI | Addressable catalog; one active model per invocation. |
| Cline/Roo | UI profile | UI profile | UI profile | UI profile | Extension-managed | Selected provider profile. |
| Crush | Custom provider entry | Provider dependent (via litellm) | Provider dependent (via litellm) | Custom openai-compatible | Env or inline key (probe-required) | Provider catalog via autodiscovery or explicit model list. |
| Kilo Code | Native/custom provider | Native/custom provider | Native/custom provider | Native/custom provider | Env/tool-auth owned; auto-fetch from /v1/models | Provider catalog via autodiscovery or explicit model map. |

## Per-provider adapter notes

### `local-openai`

Fix catalog schema output before any projection work:

- map status to `active|deprecated|experimental`;
- require a positive integer context window, deriving it from source configuration or a documented conservative fallback;
- keep booleans as booleans;
- include wire APIs and qualification state in provider status, even if the existing public catalog schema cannot yet carry every field.

No external provider file is written.

### `opencode`

Current upstream facts:

- project/global configuration uses `opencode.json` or `opencode.jsonc`;
- provider configuration is under top-level `provider` **singular**;
- selected models use `provider-id/model-id` through `model` and `small_model`;
- custom/local providers and base-URL overrides are supported.

Repository conflict:

- harness: `.opencode/config.json`, `providers` plural;
- descriptor: `.opencode/opencode.json`.

Neither should be extended in place. The implementation gate is an atomic migration/normalization plan that covers existing MCP/LSP fields and model fields in one canonical upstream-compatible file. Preserve comments if JSONC is the incumbent user file.

Target managed unit:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
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

The exact credential-reference syntax and comment-preserving writer must be runtime-verified before auto-write.

### `pi`

Repository-verified user-home shape:

```json
{
  "providers": {
    "<source-id>": {
      "baseUrl": "http://127.0.0.1:1234/v1",
      "api": "openai-completions",
      "apiKey": "<environment reference; exact syntax probe-required>",
      "compat": {
        "supportsDeveloperRole": false,
        "supportsReasoningEffort": false
      },
      "models": [
        {
          "id": "<model-id>",
          "name": "<display-name>",
          "reasoning": false,
          "input": ["text"],
          "contextWindow": 262144,
          "maxTokens": 16384,
          "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
        }
      ]
    }
  }
}
```

Rules:

- reconcile by model `id` inside an AUDiaGentic-owned provider block;
- never mutate unrelated provider blocks;
- require user-home write consent;
- runtime-verify project override, default/active model selection, key-reference behavior, and reload behavior;
- do not write a resolved key if Pi supports an env reference or ambient key path.

### `codex`

Current upstream facts (revalidated 2026-07-16 against config-basic, config-advanced, config-reference):

- CLI and IDE extension share Codex configuration;
- personal config is `~/.codex/config.toml`;
- trusted projects can add `.codex/config.toml` overrides; project-local cannot override `openai_base_url`, `chatgpt_base_url`, `apps_mcp_product_sku`, `model_provider`, `model_providers`, `notify`, `profile`, `profiles`, `experimental_realtime_ws_base_url`, `otel`;
- custom providers use `[model_providers.<id>]`; built-in provider IDs (`openai`, `ollama`, `lmstudio`) are reserved and cannot be overridden;
- `wire_api = "responses"` is the only value; this is also the default when omitted;
- built-in local `oss_provider` values include `ollama` and `lmstudio`;
- **profiles**: v0.134+ uses separate file `~/.codex/profile-name.config.toml`, selected via `--profile profile-name`; legacy `[profiles]` tables deprecated;
- **Amazon Bedrock**: built-in provider with `aws.profile`/`aws.region` overrides; use `model_provider = "amazon-bedrock"`;
- **Azure provider**: supports `query_params` (e.g., `api-version`), `request_max_retries`, `stream_max_retries`, `stream_idle_timeout_ms`;
- **auth command**: `[model_providers.<id>.auth]` table for bearer token via external process, with `command`, `args`, `timeout_ms`, `refresh_interval_ms`; do not combine with `env_key`/`experimental_bearer_token`/`requires_openai_auth`;
- **HTTP headers**: `http_headers` (static) and `env_http_headers` (from env vars) on model providers;
- **data residency**: `openai_base_url` overrides built-in OpenAI provider base URL; blocked in project-local config;
- **model catalog**: `model_catalog_json` path, overridable per profile;
- **shell environment policy**: `[shell_environment_policy]` with `inherit`, `set`, `exclude`, `include_only`;
- **auto review**: `approvals_reviewer = "auto_review"` routes eligible approvals through reviewer subagent;
- **lifecycle hooks**: inline `[hooks]` in config.toml alongside `hooks.json`;
- **network proxy**: experimental sandboxed networking with domain policies;
- **personality**/`model_reasoning_summary`: communication style and reasoning summary controls;
- **config precedence**: CLI > project (trusted only) > profile > user > system > defaults.

Target project configuration:

```toml
model = "gpt-oss:20b"
model_provider = "audiagentic_local"

[model_providers.audiagentic_local]
name = "AUDiaGentic local"
base_url = "http://127.0.0.1:1234/v1"
env_key = "AUDIAGENTIC_LOCAL_API_KEY"
wire_api = "responses"
```

Built-in local path:

```toml
model = "gpt-oss:20b"
model_provider = "ollama"
oss_provider = "ollama"
```

Amazon Bedrock path:

```toml
model_provider = "amazon-bedrock"
model = "<bedrock-model-id>"

[model_providers.amazon-bedrock.aws]
profile = "default"
region = "eu-central-1"
```

Adapter requirements:

- prefer trusted project config; note that `model_providers` is blocked in project-local config, so custom providers must be in user-level `~/.codex/config.toml`; project scope can only override `model`, `model_provider` (string selector), and other non-blocked keys;
- consent-gate user-global fallback;
- reject/mark incompatible endpoints without `/v1/responses`;
- run Responses tool-call and tool-result continuation probes, not only a basic request;
- preserve existing TOML tables/comments/order as far as the chosen TOML library permits;
- restart/reload behavior must be runtime-verified for CLI and extension;
- profile system (v0.134+) may allow per-profile managed entries via `model_catalog_json` override.

### `qwen`

Current Qwen Code supports:

- user `~/.qwen/settings.json`;
- project `.qwen/settings.json` with higher precedence;
- multiple `modelProviders`;
- multiple protocol families; and
- switching with `/model`.

This supersedes the earlier single-model/no-config assumption. Qwen is a P1 project-structured adapter candidate.

Requirements:

- use project settings by default;
- preserve user/project precedence and avoid duplicating user-level providers unnecessarily;
- reconcile providers/models by stable IDs;
- test merge semantics when both scopes define `modelProviders`;
- separately own any active model pointer;
- runtime-verify exact schema for OpenAI-compatible base URL, env key reference, context/output fields, and reload behavior.

### `crush` — new candidate

Crush is worth adding because it explicitly supports local provider types and model autodiscovery. Current upstream documents provider types including `llamacpp`, `lmstudio`, `litellm`, and `ollama`.

Example local block:

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

Recommended adapter stance:

- add as P1 after shared JSON managed-config support;
- prefer project config where precedence is runtime-verified;
- allow the provider to discover models when safe, but persist a filtered explicit list when deterministic profile validation is required;
- record discovered context windows as observations, not silently as desired-state overrides;
- validate API-key reference syntax, config precedence, and hot reload/restart behavior.

### `kilo` — new candidate

Kilo Code is worth adding because its CLI and editor surfaces use shared JSON/JSONC provider configuration, and current documentation supports custom OpenAI-compatible providers plus `/v1/models` discovery.

Current CLI config is OpenCode-derived and uses `kilo.jsonc`; model IDs follow `provider_id/model_id`. Local LM Studio and custom provider examples use top-level `provider` with a models map.

Recommended adapter stance:

- P1 structured project adapter;
- use the same parse/merge model as OpenCode, but a separate descriptor/schema and file path;
- preserve JSONC comments;
- do not assume every OpenCode key/version applies unchanged—validate the installed Kilo schema;
- credentials remain env/tool-auth owned;
- own provider entries and model/default pointers separately.

### `goose`

The earlier “unknown JSON provider config” position is obsolete. Current Goose supports many native providers, local providers, and custom providers. Upstream configuration is user-scoped by default, with launch-time provider/model overrides also available.

Recommended sequence:

1. implement the execution bridge;
2. implement `launch-only` projection first using documented Goose provider/model/base URL/key environment mechanisms;
3. runtime-verify whether a project-local config override exists;
4. if no project scope exists, add a consented user-config adapter for the platform-specific Goose config location;
5. keep secret material in Goose’s supported secret store/env path, not inline in the managed fragment;
6. model config changes generally take effect in a new session, so report reload as `restart-session`.

Do not project model settings into the repository’s project `.goose/config.yaml` merely because MCP currently uses that path; prove that the installed Goose reads model providers there.

### `continue`

Current upstream prefers `config.yaml`; `config.json` is deprecated. Current YAML contains both models and `mcpServers`, so the repository must not split these managed kinds across legacy JSON and YAML.

Required migration rule:

- detect the installed Continue generation and incumbent files;
- for current versions, create one atomic JSON→YAML migration plan covering MCP + models;
- preserve unmanaged models, roles, capabilities, rules, context, prompts, and MCP servers;
- for explicitly pinned legacy Continue only, continue to manage JSON;
- never manage MCP in JSON and models in YAML simultaneously.

Example current YAML:

```yaml
name: AUDiaGentic project
version: 0.0.1
schema: v1
models:
  - name: Qwen local
    provider: openai
    model: qwen3-coder
    apiBase: http://127.0.0.1:1234/v1
    roles: [chat, edit, apply]
    capabilities:
      - tool_use
mcpServers: []
```

Credential references and exact model-capability spelling are runtime/schema validation items; do not add a credential field until the installed schema’s non-literal secret mechanism is verified. Continue can use Responses for applicable OpenAI models and can be configured to use Chat Completions where needed, so wire choice must be represented per model.

### `openhands`

Treat OpenHands as versioned:

- **legacy V0**: `config.toml` and named LLM sections may be a structured surface;
- **current V1/SDK flows**: provider/model/base URL/key are primarily UI/env/SDK concerns. Agent Canvas is the new developer control center that runs multiple agents (OpenHands, Claude Code, Codex, Gemini CLI) via ACP. LLM profiles (up to 10 per account) allow mid-conversation model switching. ACP agents authenticate via subscription login or API key.

Because the repository execution adapter is still a stub, the portable first implementation is launch projection after the bridge exists:

```text
LLM_MODEL=<provider-prefix>/<model-id>
LLM_BASE_URL=<base-url>
LLM_API_KEY=<resolved-at-launch>
```

Exact variable names and the required “override with env” behavior must be checked against the installed version. Do not write legacy `[llm]` TOML for a V1 runtime.

### `zed` — new candidate

Zed is worth adding as an editor-agent consumer because it has a documented, public settings surface for custom OpenAI-compatible and Anthropic-compatible models. It can select Chat Completions or Responses per OpenAI-compatible model.

Example model-only entry:

```json
{
  "language_models": {
    "openai_compatible": {
      "audiagentic-local": {
        "api_url": "http://127.0.0.1:1234/v1",
        "available_models": [
          {
            "name": "qwen3-coder",
            "display_name": "Qwen local",
            "max_tokens": 262144,
            "max_output_tokens": 16384,
            "capabilities": {
              "tools": true,
              "images": false,
              "parallel_tool_calls": false,
              "chat_completions": true
            }
          }
        ]
      }
    }
  }
}
```

Rules:

- manage model metadata only after user-global write consent;
- never place API keys in `settings.json`;
- credentials stay in Zed’s keychain or documented environment variable;
- if `chat_completions` is false, qualify `/v1/responses` and tool continuation;
- Zed’s model access config applies to Zed Agent and Zed-owned AI features, not to external agents running inside Zed.

### `aider`

Implement launch env/args once execution exists:

- model flag/prefix;
- OpenAI-compatible base URL;
- API-key env reference/resolution;
- optional context/window metadata only where Aider supports it.

A `.aider.conf.yml` writer remains secondary and blocked until scope, merge, removal, and secret-reference behavior are tested. Do not add persistent config merely to avoid implementing the launch bridge.

### `cline` and `roo`

Cline now has three provider paths: Cline usage-billing (OAuth via Google/GitHub/email), ClinePass ($9.99/mo subscription), and BYOK (Bring Your Own Key). The IDE settings UI provides an API Provider dropdown with named providers including OpenRouter, Anthropic, OpenAI, Google Gemini, AWS Bedrock, DeepSeek, plus Ollama/LM Studio for local runtimes. CLI `cline auth` still works for BYOK. However, the stable user-facing surface remains extension-managed profiles/UI. Keep model endpoint automation manual until there is a public configuration API or a validated host adapter.

- do not hard-code VS Code global-storage paths;
- do not mutate opaque extension state databases;
- correct Roo’s descriptor if `access_mode: env` inaccurately describes extension profile ownership;
- status should provide exact manual steps and indicate that AUDiaGentic cannot verify the selected extension profile without a host adapter.

Kilo Code is not grouped here because its current CLI/editor configuration has a documented JSONC surface suitable for managed config.

### `plandex`

Keep blocked until the installed tool’s custom provider/model pack schema, scope, merge behavior, and reload behavior are documented and tested. OpenAI compatibility alone does not justify a writer.

### Native-account-only and excluded consumers

- Claude Code: native Anthropic/account path and supported enterprise backends; add a dedicated gateway recipe only when its documented base-URL/auth contract matches a source.
- Gemini CLI: native Google account/API path; not a generic OpenAI-compatible endpoint consumer.
- GitHub Copilot: account-derived catalog; no generic endpoint projection.
- Cursor: treat as native/manual unless a stable public custom-provider configuration surface is verified.
- Antigravity: managed-agent API research, not model-endpoint propagation.

## Descriptor metadata

The model kind should use the same sibling-field pattern as MCP/LSP while sharing one underlying spec type:

```yaml
model_config:
  config_path: "opencode.jsonc"
  reader: "...:read_opencode_models"
  writer: "...:write_opencode_models"
  remover: "...:remove_opencode_models"
  format: "opencode-jsonc"
  scope: project
  refresh_mode: restart-session
  consent: none

supported_connectors:
  openai-compatible:
    wire_apis: [chat-completions, responses]
  anthropic:
    wire_apis: [messages]

projection_modes:
  custom-entries:
    supported: true
  native-key-env:
    supported: false

vendor_key_injection:
  anthropic:
    mechanism: env
    key: ANTHROPIC_API_KEY
```

Recommended additions to `ManagedConfigSpec`:

- `scope: project|user|editor-global|host-managed`;
- `consent: none|required`;
- `refresh_mode: file-watch|reload-command|restart-session|restart-host|none`;
- `supports_comments`;
- `schema_probe_fn`;
- `qualification_profile`;
- optional `path_candidates` resolved by a probe rather than guesswork.

Do not create separate long-lived spec dataclasses for each managed kind.

## Service shape

Runtime descriptors and the tested providers public API are authoritative. The
current boundary is:

- model-source CRUD persists desired state only;
- `manage_model_projection(provider_id, mode, request)` is the single public
  provider-file automation operation;
- provider reconciliation builds a typed `ModelProjectionRequest` and calls
  that operation;
- explicitly registered handlers render provider-native entries and reuse
  `ManagedConfigSpec`, `ManagedFragmentRegistry`, and `sync_managed_config`;
- absence of registration is sufficient for unsupported or blocked providers.

Do not recreate public sync/list/reload routes, `NoAutomationRecipe` objects,
launch-env projection families, or speculative qualification caches from the
historical design notes in this document.

### Source-management tools

All mutations validate and write `.audiagentic/config/model-sources.yaml`. They
do not apply provider configuration implicitly:

- `model_source_list()`
- `model_source_add(source_id, config)`
- `model_source_update(source_id, updates)`
- `model_source_remove(source_id)`
- `model_source_set_enabled(source_id, enabled)`
- `model_vendor_set_enabled(vendor_id, enabled)` updates all configured sources
  in one vendor group;
- `list_model_inventory()` joins configured sources, cached/static catalogs,
  native harness catalogs, and verified harness projection modes;
- `refresh_model_source_catalog(source_id)` is the explicit network/cache
  mutation;
- `apply_model_sources()` projects enabled custom endpoints/catalog entries
  across all enabled compatible harnesses.

### Projection tools

- `manage_model_projection(provider_id, mode, request)` remains the internal
  typed provider-family boundary with `plan|apply|prune|status`; it is not the
  user-facing MCP workflow;
- existing runtime catalog operations remain distinct: `list_provider_models`, `refresh_provider_catalog`, `refresh_all_catalogs`.

### Status fields

At minimum expose:

- support mode;
- config path and scope;
- consent state;
- managed entry count;
- unmanaged collision count;
- refresh/reload mode;
- source catalog freshness;
- materialized vs runtime-discoverable discrepancy count;
- qualification state and required wire API;
- last successful sync/probe;
- classified error and `action_needed`.

### Error classes

Use stable machine-readable classifications:

- `CONFIG_PATH_UNRESOLVED`
- `CONFIG_SCHEMA_UNSUPPORTED`
- `CONFIG_PARSE_FAILED`
- `UNMANAGED_COLLISION`
- `CONSENT_REQUIRED`
- `SECRET_REFERENCE_MISSING`
- `CATALOG_REFRESH_FAILED`
- `MODEL_NOT_DISCOVERABLE`
- `WIRE_API_UNSUPPORTED`
- `ENDPOINT_AUTH_FAILED`
- `ENDPOINT_UNREACHABLE`
- `TOOL_CALL_UNSUPPORTED`
- `TOOL_CONTINUATION_FAILED`
- `ROLE_INCOMPATIBLE`
- `RELOAD_REQUIRED`
- `EXECUTION_BRIDGE_MISSING`

Do not collapse protocol failure into “model unavailable.”

## Implementation constraints

Do not:

- clone `services/mcp.py` into a second full model service;
- add a third hard-coded registry module;
- add another persistent `*ConfigSpec` class;
- write provider model config from recipes;
- patch JSON/TOML/YAML/JSONC with text substitutions;
- resolve and persist secrets in managed fragments;
- treat a successful `/models` call as agent compatibility;
- equate Chat Completions support with Responses support;
- manage the same provider’s MCP and model settings in divergent legacy/current files;
- automate VS Code extension storage by implementation detail;
- claim a launch-only integration works for independently launched sessions;
- turn every hosted OpenAI-compatible service into a new connector.

## Review gates

| Gate | Required evidence |
|---|---|
| `local-openai` catalog | Payload validates against `provider-model-catalog.schema.json`; context window and status are valid. |
| Shared core | Existing MCP and LSP tests pass unchanged through generalized managed-config infrastructure. |
| Source schema | Both v1 classes validate; semantic behavior is documented; wire APIs, filters, secret refs, overrides, and qualification policy are tested. |
| Secret safety | No resolved key appears in source files, registries, dry-run output, logs, status, exceptions, or timelines. |
| Structured adapter | Preserves unmanaged entries/comments where applicable; removes only owned entries; reports collisions. |
| Scope/consent | Project path is preferred; user/editor-global writes are dry-runnable and explicitly consented. |
| Protocol qualification | Required agent-loop probes pass for the selected provider/model/wire API. |
| Discovery degradation | Catalog failure retains valid cache and reports stale/action-needed without blocking unrelated sync. |
| Runtime discrepancy | Materialized model missing from provider catalog is surfaced, not silently accepted. |
| Env projection | Launch env receives values without fragment registry use or secret logging; standalone limitation is reported. |
| Migration | OpenCode path/schema and Continue JSON→YAML transitions are atomic across MCP/LSP/models. |
| Manual providers | Cline/Roo/native account paths give precise action-needed guidance without pretending automation. |
| Documentation | This file and per-provider evidence notes are updated whenever a provider schema/path/protocol fact changes. |

## Recommended implementation order

1. Fix `local-openai` catalog validation and add regression tests.
2. Extract `ManagedConfigSpec`, `ManagedFragmentRegistry`, and shared sync/reload infrastructure without changing MCP/LSP behavior.
3. Extend the source schema with wire APIs, secret header refs, and qualification policy; document v1 naming debt.
4. Implement the endpoint qualification service and error taxonomy.
5. Resolve and migrate OpenCode to current upstream `opencode.json(c)` + `provider` singular across MCP/LSP/models.
6. Implement Codex project TOML with mandatory Responses qualification.
7. Implement Pi with consented user-home writes and default/reload probes.
8. Add Qwen project `modelProviders` with merge/collision/default-pointer tests.
9. Add Crush as a project structured adapter.
10. Add Kilo as a project JSONC structured adapter.
11. Implement Goose execution and launch-only projection; add persistent user adapter only after scope/secret tests.
12. Migrate Continue atomically from legacy JSON to current YAML, including MCP and models.
13. Implement OpenHands and Aider launch projections once their execution bridges exist.
14. Add Zed model metadata projection with user consent; leave credentials to keychain/env.
15. Reassess Plandex after schema discovery.
16. Keep Cline/Roo/manual account providers blocked until stable host/config APIs exist.

## Open validation list

| Provider | Remaining runtime/repository validation |
|---|---|
| `local-openai` | Catalog schema fix and propagation of wire/qualification status. |
| `opencode` | Canonical path migration, JSON vs JSONC precedence, secret reference, comment preservation, reload, MCP/LSP coexistence. |
| `pi` | Project override, default/active model selection, API key reference, reload. |
| `codex` | Installed version of profiles (v0.134+), Amazon Bedrock built-in provider, Azure provider with query_params, auth commands, HTTP headers, model catalog JSON, shell environment policy, auto review, lifecycle hooks inline, network proxy, personality/reasoning summary; project-local `model_providers` block enforcement; Responses tool-result compatibility; reload/restart. |
| `qwen` | Exact `modelProviders` schema for custom base URLs, project/user merge behavior, active model pointer, reload. |
| `crush` | Exact project/global path precedence, key refs, explicit-model vs discovery merge, reload. |
| `kilo` | Installed schema compatibility with OpenCode-derived fields, project/global precedence, JSONC preservation, editor/CLI reload. |
| `goose` | Execution bridge, project override existence, platform config paths, custom-provider file schema, secret store, session reload. |
| `continue` | Installed generation, JSON→YAML migration, secret syntax, project/user path, file watch/reload. |
| `openhands` | V0 vs V1 detection, current env/SDK variable semantics, execution bridge. |
| `zed` | Settings scope and merge behavior, per-model wire API selection (chat_completions vs responses), reasoning_effort support, capabilities model, custom headers, local provider autodiscovery (llama.cpp/Ollama/LM Studio), keychain secret storage, settings reload, default model pointer. |
| `aider` | Execution bridge, model/base URL args, persistent YAML merge only if later needed. |
| `cline` | Public profile/config API or host adapter. |
| `roo` | Descriptor access-mode correction and public profile/config API. |
| `plandex` | Custom provider schema/path/scope/model packs/reload. |
| Native account providers | Only dedicated account/gateway recipes; no generic endpoint projection without verified contract. |

## Upstream evidence index

These links are evidence for upstream product capability only. Repository and installed-runtime facts still require their own tests.

- OpenAI Codex: [Config basics](https://developers.openai.com/codex/config-basic), [Advanced configuration](https://developers.openai.com/codex/config-advanced), [Configuration reference](https://developers.openai.com/codex/config-reference)
- OpenCode: [Config](https://opencode.ai/docs/config/), [Providers](https://opencode.ai/docs/providers/), [Models](https://opencode.ai/docs/models/), [Zen](https://opencode.ai/docs/zen/)
- Qwen Code: [Settings](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/settings/), [Model Providers](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/model-providers/), [Authentication](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/)
- Continue: [YAML reference](https://docs.continue.dev/reference), [YAML migration](https://docs.continue.dev/reference/yaml-migration), [OpenAI-compatible providers](https://docs.continue.dev/customize/model-providers/top-level/openai)
- Goose: [AAIF Goose repository](https://github.com/aaif-goose/goose)
- Crush: [Crush repository and configuration examples](https://github.com/charmbracelet/crush)
- Kilo Code: [OpenAI-compatible providers](https://kilo.ai/docs/ai-providers/openai-compatible), [CLI configuration](https://kilo.ai/docs/code-with-ai/platforms/cli), [Custom models](https://kilo.ai/docs/code-with-ai/agents/custom-models)
- Zed: [LLM Providers](https://zed.dev/docs/nightly/ai/llm-providers.md), [Use API Access](https://zed.dev/docs/nightly/ai/use-api-access.md), [Use a Local Model](https://zed.dev/docs/nightly/ai/use-a-local-model.md)
