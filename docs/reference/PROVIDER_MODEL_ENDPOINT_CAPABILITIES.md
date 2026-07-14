# Provider Model Endpoint Capabilities

Status: reference draft
Last validated: 2026-07-09
Planning set: `docs/planning/active/model-endpoint-management/MO01..MO06`

This document records how AUDiaGentic should reason about local/custom model endpoint configuration across provider adapters. It is provider-owned: agent profiles choose `provider_id` and `model_id` at dispatch time, while the `providers` component owns the config formats, auth conventions, model catalogs, reload behavior, and projection rules that make a model available to each provider.

> **Placeholder legend.** Cells marked `⟨FILL⟩` are fields whose value has not been verified against the installed upstream tool or this repo's own adapter code. Do not guess them. Confirm against the installed tool version or repository implementation, then replace the token. A `⟨FILL⟩` value is a blocker for auto-writing that provider, not a default.

## Goal

Declare a local/custom model endpoint once in AUDiaGentic project config, then let the `providers` component project that desired state into each compatible third-party agent's own config format so every supported provider can drive an AUDiaGentic-hosted model without clobbering unmanaged user entries and with reversible ownership tracking.

This is the same problem shape AUDiaGentic already handles for managed MCP server entries and language-server projection: one desired-state declaration, multiple provider-specific config surfaces, and ownership tracking so manually added user entries survive. Model endpoint propagation is therefore a **managed-config kind**, not a separate subsystem.

## Current code facts this plan must respect

The current repository has useful primitives, but the consolidation is not implemented yet.

| Area | Current code state | Planning consequence |
|---|---|---|
| Provider config specs | `McpConfigSpec` and `LanguageServersConfigSpec` are still separate dataclasses in `components/providers/descriptors/base.py`. MCP has `refresh_mode`, `reload_fn`, and `remote`; LSP currently does not. | MO06 must extract a `ManagedConfigSpec` that supports optional/feature-specific fields. Do not claim the shared spec already exists. |
| Descriptor loading | `loader.py` still has `_build_mcp_config` and `_build_language_servers_config` as separate builders. | MO06 must replace both with one builder or a managed-config map while keeping YAML compatibility. |
| Reconciler | `foundation/toolchains/fragments.py` is already domain-opaque: `FragmentStore`, `reconcile_fragments`, opaque `owner_scope`, and `Any` payloads. | Reuse this directly for structured model entries. Do not create another reconciler. |
| Registry | `managed_mcp_registry.py` is a provider-specific JSON registry hard-coded to `.audiagentic/runtime/providers/managed-mcp-servers.json`. | Generalize it into a parameterized `ManagedFragmentRegistry`; instantiate one registry for MCP and one for model endpoints. |
| MCP sync service | `services/mcp.py` contains the reusable sync/reload shape: resolve config path, bind `FragmentStore`, call `reconcile_fragments`, then reload or report no-op. | Extract shared `sync_managed_config` / `reload_managed_config`; MCP/LSP/model wrappers should stay thin. |
| Recipe framework | `ProviderRecipeKind` currently has no `MODEL_CONFIG`/`MODEL_ENDPOINTS` kind. `NoAutomationRecipe` is guidance-only and returns `ABSENT` plus `action_needed`. | Add an explicit model-config recipe kind. Use `NoAutomationRecipe` only for manual/unsupported/blocked providers, not for env-projection automation. |
| OpenCode harness | The runtime harness writes `.opencode/config.json` with top-level `providers`, while the provider descriptor currently manages MCP/LSP in `.opencode/opencode.json`. | OpenCode model config is a validation gate before implementation. Unify or intentionally separate these paths atomically. |
| Goose descriptor | The repo's Goose provider uses `.goose/config.yaml` for MCP and its execution adapter is currently a stub. | Do not assume a JSON custom-provider model config. Treat Goose model config as validate-first until path/schema are confirmed. |
| Codex config scope | Descriptor manages **project** `.codex/config.toml` for MCP (`remote: false`) and LSP — not the user-global file. | Prefer project-scope `model_providers` if the installed Codex honors it; user-global `~/.codex/config.toml` is the consent-gated fallback only. |
| OpenHands config surface | Descriptor manages `.openhands/config.toml` for MCP; `settings.json` is never touched by this repo. | Re-aim the gate at `config.toml` `[llm]` semantics; structured-file preferred, env projection fallback. |
| Continue config surface | Descriptor manages `.continue/config.json` (JSON) for MCP. | Extend the incumbent `config.json` with `models[]` first; YAML only if the installed version requires it, migrated atomically with MCP (§10). |
| Pi model surface scope | Harness template `home/agent/models.json` is **home-scoped**; shape verified (`providers.<id>`: baseUrl/api/apiKey/compat/models[]). | Pi model writes are user-home writes; verify project override + reload before marking the adapter complete. |
| Provider execution stubs | `aider`, `openhands`, `goose`, `plandex` have `execution: stub`; `roo` is `unsupported` (and `access_mode: env`). | Env-projection adapters are inert until the execution bridge is real; keep those pairs manual/blocked in status meanwhile. |
| local-openai catalog | `local_openai/catalog.py` emits `status: "available"` and `context-window: None`, while the schema requires `status ∈ {active,deprecated,experimental}` and integer `context-window >= 1`. | MO05 remains the first isolated bug fix before broader endpoint projection. |

## Design position

Model endpoint projection belongs under the providers component.

- `agents` keep provider/model binding and execution selection.
- `providers` own endpoint declaration, connector compatibility, provider config rendering, auth projection, reload/refresh behavior, and provider status.
- Recipes call provider-owned sync/status operations; recipes must not hand-write provider config files directly.
- Structured config adapters must preserve unmanaged provider entries.
- Env-projection providers must not be forced through fragment reconciliation.
- VS Code extension-storage providers must stay manual/blocked until storage profile format and host-adapter access are validated.

## Model source classes

A **model source** is the AUDiaGentic-side declaration of where models come from. There are exactly two source classes — a closed enum. The real boundary is *declared vs connected*: local endpoints are fully described by their declaration; remote accounts involve a key, discovery, and degradation handling. "Frontier vendor" vs "account aggregator" is a **descriptive grouping** (a column in the mapping table below), NOT a schema class — the two behave identically in code (connector + discovery drive everything), so they must never become separate code paths or registry keys.

| Source class | What it is | Enablement semantics | Account managed by AUDiaGentic? |
|---|---|---|---|
| `local-endpoint` | An individually configured endpoint (llama.cpp, vLLM, LM Studio, Ollama, any gateway URL) | Declaring the source declares exactly one endpoint+model; declare several sources for several local models | N/A — local |
| `remote-account` | Any keyed external service: frontier vendors (OpenAI/ChatGPT, Anthropic, Google Gemini, xAI, Mistral…) and account aggregators (OpenRouter, OpenCode Zen, Qwen portal, Together, Groq…) | Enabling the source establishes connectivity and enables its model set per discovery + per-provider projection mode below | No — we hold only a key reference; the account and its entitlements stay the user's |

### Discovery vs projection — two separate axes

**Discovery** is what AUDiaGentic knows about the source's models (feeds aliases, defaults, status). Closed enum on the source:

- `static-catalog` — model set ships as a curated data file under `src/audiagentic/config/providers/model-catalogs/<source-id>.yaml` (config-over-code; updating a vendor family is a data change).
- `list-api` — model set is fetched from the source's models API (OpenAI `/v1/models`, OpenRouter `/models`). Refresh is **best-effort and never blocks sync**: on failure, keep the last cached catalog, emit a warning + `action_needed`, continue (see error-classification item MO08).
- `none` — AG holds no model list for the source (aliases cannot target it; connectivity projection still works).

**Projection** is how each agent provider gets the source, chosen per `(agent provider, source)` from the provider's declared capabilities — never by `if/elif`:

1. `native-key-injection` (preferred where declared) — the agent natively supports the vendor/aggregator and needs only the key. Two mechanisms: `env` (the tool reads a well-known env var, e.g. `OPENROUTER_API_KEY`) or `config` (a key/base-url field written into the agent's config — a managed fragment, id `model-connections/<source-id>`; prefer the tool's own env-indirection syntax over literals where supported). In this mode the agent enables **all** of the vendor's models itself; `model-filter` does not apply and this must be surfaced in status rather than silently ignored.

   **Standalone rule (providers run outside AG):** agents run in the user's own environment as the normal case — AG manages config externally; AG-launching is a separate capability. Enablement must therefore hold WITHOUT AG in the launch loop: for the `env` mechanism the var must exist in the **ambient user environment** (AG verifies presence via `has_ambient_value` and emits `action_needed` "set `<VAR>` user-globally" when absent — it never sets it). The AG launch-env contribution seam is a **supplement** for AG-launched sessions only; a pair whose only working channel is launch-env reports status "works in AG-launched sessions only", never plain auto/enabled.
2. `custom-entries` (fallback where the connector is supported) — AG materializes explicit model entries into the agent's config from the discovered model set. `model-filter` (optional include/exclude patterns on the source) applies here and to AG-side alias exposure — mandatory in practice for `list-api` aggregators, whose raw lists run to hundreds of models.
3. `none` — the agent cannot carry this source.

Provider YAML declares its capability map: `vendor-key-injection: {<vendor-id>: {mechanism: env|config, key: <env-var-or-config-path>}}` plus the existing `supported-connectors` for the custom-entries path. Every cell is ⟨FILL⟩ until verified per provider (MO09 deep dive).

Materialization rule: a source produces zero or more desired entries for the same reconcile machinery MO02 builds — sources are an input layer above the desired-entry builder, not a second sync path.

- `local-endpoint` → one entry, managed id `model-endpoints/<source-id>` (unchanged from the original shape).
- `remote-account` via `custom-entries` → entries keyed `model-endpoints/<source-id>/<model-id>` (post-filter).
- `remote-account` via `native-key-injection` (config mechanism) → one connectivity entry, managed id `model-connections/<source-id>`; (env mechanism) → launch-env contribution, no fragment.

Ownership, preserve-unmanaged, collision, and removal rules are identical for all classes.

### Upstream service → source mapping (running reference)

Keep this table current whenever a new external source is enabled or verified. Rows here are *model sources*; the capability matrix further down lists *agent providers* (consumers) — the two must not be conflated. `Grouping` is descriptive terminology only (never a code branch). `Support` is the recommended AUDiaGentic rollout priority.

| Upstream service | Class | Grouping | Connector | Model discovery | Support | Notes |
|---|---|---|---|---|---|---|
| Local llama.cpp / vLLM / LM Studio / llama-swap | `local-endpoint` | local | `openai-compatible` | n/a (declared) | P1 | One source per configured model. |
| Ollama (local daemon) | `local-endpoint` | local | `ollama` or `openai-compatible` shim | n/a (declared) | P1 | Prefer native connector only where the consumer supports it. |
| OpenAI (ChatGPT models) | `remote-account` | frontier vendor | `openai-compatible` | `list-api` (⟨FILL⟩ verify auth scope) | P1 | Family enabled as a set; broad native agent support expected. |
| Anthropic (Claude models) | `remote-account` | frontier vendor | `anthropic` | `static-catalog` (no public list API assumed — ⟨FILL⟩ verify) | P1 | Family enabled as a set. |
| Google (Gemini models) | `remote-account` | frontier vendor | `gemini` | `list-api` (⟨FILL⟩ verify) | P1 | Family enabled as a set. |
| OpenRouter | `remote-account` | aggregator | `openrouter` | `list-api` (`/models`) | P1 | Account/plan determines usable subset; `model-filter` mandatory for custom-entries projection. |
| OpenCode Zen | `remote-account` | aggregator | `openai-compatible` (⟨FILL⟩ verify) | ⟨FILL⟩ | P2 | Key-injection into OpenCode expected; verify beyond OpenCode. |
| Qwen portal / DashScope (account service) | `remote-account` | aggregator | `openai-compatible` (⟨FILL⟩ verify) | ⟨FILL⟩ | P2 | Distinct from the `qwen` agent provider (consumer). |
| xAI (Grok) | `remote-account` | frontier vendor | `openai-compatible` (⟨FILL⟩ verify) | ⟨FILL⟩ | P2 | Add when an agent provider verifies native support. |
| Mistral | `remote-account` | frontier vendor | `openai-compatible` (⟨FILL⟩ verify) | ⟨FILL⟩ | P2 | — |
| DeepSeek | `remote-account` | frontier vendor | `openai-compatible` (⟨FILL⟩ verify) | ⟨FILL⟩ | P2 | — |
| Groq / Together | `remote-account` | aggregator | `openai-compatible` (⟨FILL⟩ verify) | ⟨FILL⟩ | P2 | Hosted open-model serving; aggregator semantics. |
| LiteLLM proxy (self-hosted) | `remote-account` | aggregator | `litellm` | ⟨FILL⟩ | P2 | Aggregator semantics even when self-hosted. |
| Azure OpenAI / AWS Bedrock / GCP Vertex | `remote-account` | cloud platform | ⟨FILL⟩ | ⟨FILL⟩ | P3 (deferred) | Platform auth (deployments/IAM) differs from key-ref shape — needs its own validation before any contract change. |

### Relationship to profiles, aliases, and defaults (decided)

- Agent profiles keep binding `provider_id` + `model_id` only; they never reference sources or endpoints directly.
- `default-model` and model aliases resolve against the union of models materialized by **enabled** sources; disabling a source invalidates its aliases with a clear VAL error, never a silent fallback.
- Enabling/disabling a source mutates project config (`.audiagentic/config/model-sources.yaml`) followed by sync — either by direct edit or through the `model_source_*` management tools (see Service shape), which validate against the schema and write the same file. Provider config files are never the mutation surface.

### Availability vs materialization (decided, RV264)

For providers with a `fetch_catalog_fn` (installed-tool CLI discovery — repo fact: OpenCode's `opencode models --verbose` fetcher), the post-refresh **runtime catalog is authoritative** for which models the tool can actually use right now. Source materialization and catalog refresh are two different, complementary operations, not the same fact observed twice:

- Source materialization **adds** models to the tool (writing a `model-endpoints/<source-id>` entry into the tool's own config).
- Catalog refresh **observes** what the tool currently has available (via `fetch_catalog_fn`), independent of whether AUDiaGentic materialized it.

Agent-profile/alias model **validation** resolves against the runtime catalog where one exists for that provider; against the materialized-source union otherwise (providers with no `fetch_catalog_fn`, e.g. structured-file-only adapters). A managed/materialized entry that goes missing from the next tool catalog read is a **reconcile discrepancy** — surfaced via provider status/`action_needed` (status fields land in MO02; the read surface is MO10's extended `list_provider_models`) — never silent success and never a validation that just happens to pass anyway.

Do not widen the source-level `model-discovery` enum for this: tool-CLI discovery is a **provider** property, already modeled by `fetch_catalog_fn` on the descriptor — not a **source** property. `model-discovery` stays scoped to what AUDiaGentic itself knows about a `remote-account` source's model set (static-catalog/list-api/none); it says nothing about what a specific agent tool can currently execute.

First consumer: the reviewer-agent plan (RA01) binds a Reviewer profile to `provider=opencode` plus a model from the OpenCode runtime catalog — this section's availability definition is what makes that binding validatable.

## Managed mechanisms

| Mechanism | Use for | Managed unit | Ownership model | Implementation vehicle |
|---|---|---|---|---|
| Structured managed config | Pi, OpenCode, Codex, Qwen, Continue, Plandex after validation, Goose only after validation | Provider block, model entry, or provider+model tuple | `owner_scope = provider_id`, `managed_id = model-endpoints/<endpoint-id>` | `ManagedConfigSpec` + `ManagedFragmentRegistry` + `sync_managed_config` over `reconcile_fragments` |
| Native AUDiaGentic catalog | `local-openai` | AG catalog entry/alias | AG-owned catalog record | Fix catalog schema output, expose endpoint entries as provider catalog models |
| Launch env projection | OpenHands, Aider, possibly Goose if file path remains unvalidated | Env vars and launch args | No persistent fragment ownership | Provider capability recipe that contributes launch env; no fragment registry |
| Extension storage/manual | Cline, Roo | VS Code extension profile state | No stable managed contract yet | `NoAutomationRecipe` with action-needed text until storage format validated through host adapter |
| Native vendor/account service | Gemini CLI, Claude Code, Copilot | Native model selection/account catalog | Not a local endpoint entry | No generic custom endpoint projection unless a vendor-gateway recipe is explicitly added |
| Managed-agent API | Antigravity | Remote agent id/session | Not a local model endpoint | Research-only, out of model-endpoint propagation scope |

## Proposed managed model shape

The contract's top-level key is `sources` (implemented: `contracts/model-sources.schema.json`), and the canonical declaration file is `<project-root>/.audiagentic/config/model-sources.yaml` (project-scoped, sibling to `agent-profiles.yaml` — same precedent). A `local-endpoint` source carries the full endpoint field set inline (this is the original `model-endpoints` shape, now one class of two). `remote-account` sources carry connectivity + discovery instead of a single model id.

```yaml
contract-version: v1
sources:
  qwen36-local:
    source-class: local-endpoint
    display-name: Qwen3.6 local
    connector: openai-compatible
    base-url: http://127.0.0.1:1234/v1
    api-key-ref: env:AUDIAGENTIC_LOCAL_API_KEY
    model-id: qwen3.6-35b-a3b
    context-window: 262144
    max-output-tokens: 4096
    capabilities:
      tool-use: true
      reasoning: false
      vision: false
    provider-overrides:
      pi:
        api: openai-completions
        compat:
          supportsDeveloperRole: false
          supportsReasoningEffort: false
      opencode:
        provider-id: audiagentic-local
      openhands:
        model-prefix: openai/
  anthropic-account:
    source-class: remote-account
    display-name: Anthropic (Claude)
    connector: anthropic
    api-key-ref: env:ANTHROPIC_API_KEY
    model-discovery: static-catalog
    enabled: true
  openrouter-main:
    source-class: remote-account
    display-name: OpenRouter
    connector: openrouter
    base-url: https://openrouter.ai/api/v1
    api-key-ref: env:OPENROUTER_API_KEY
    model-discovery: list-api
    model-filter:            # applies to custom-entries projection + AG-side aliases only;
      include:               # native key injection always enables the agent's full vendor set
        - "anthropic/*"
        - "qwen/*"
      exclude:
        - "*-preview"
    enabled: true
  opencode-zen:
    source-class: remote-account
    connector: openai-compatible
    api-key-ref: env:OPENCODE_ZEN_API_KEY
    model-discovery: none   # no AG-side model list until a list API is verified
    enabled: true
```

Stable ownership rules:

- Use `model-endpoints/<source-id>` (local-endpoint), `model-endpoints/<source-id>/<model-id>` (catalog/list-derived), or `model-connections/<source-id>` (connection-only) as the stable managed id passed to the reconciler.
- Keep `owner_scope` as the AUDiaGentic provider id, matching current MCP registry semantics.
- Provider-visible names may vary by adapter; the stable managed id must not.
- Updating URL, model id, context window, output limit, or provider overrides updates only the owned entry.
- Removing an endpoint removes only entries owned by that endpoint id.
- Unmanaged user-defined provider/model entries must survive every sync.

## Connector taxonomy

`openai-compatible` is only one connector. The endpoint declares its connector; each provider declares `supported-connectors`; projection occurs only when the provider can carry the endpoint's connector or a declared provider override maps to a supported fallback.

Connector-specific parameters (anthropic API version, gemini API version, openrouter routing preferences / namespaced model ids, ...) live in a single free-form `connector-options: map[string, any]` field on the source (RV323) — the v1 schema does not hardcode a per-connector sub-schema. As MO09 verifies a connector's required/known keys, document them in the per-connector rows below and enforce them in the relevant renderer/adapter code, not by changing the schema. No connector currently has verified required `connector-options` keys; first-wave connectors (`openai-compatible`, `ollama`) need none beyond the base fields.

| Connector | Wire/backend | Auth shape | Notes |
|---|---|---|---|
| `openai-compatible` | OpenAI-style `/v1` chat/completions or compatible gateway | Bearer/API key + base URL | Baseline for llama.cpp, vLLM, LM Studio, Ollama OpenAI shim, and many gateways. |
| `anthropic` | Anthropic Messages API | `x-api-key`, version header, optional base URL | Native Claude/gateway path; not the same as OpenAI-compatible. |
| `gemini` | Google Generative Language API | API key or OAuth + API version | Native Gemini connector; distinct from Gemini's OpenAI-compatible shim as consumed by other clients. |
| `openrouter` | OpenAI-compatible wire plus OpenRouter routing/catalog extensions | Bearer key | Treat as first-class where provider has native OpenRouter support because routing/catalog semantics matter. |
| `litellm` | LiteLLM prefix abstraction | Backend-specific env keys | Routing abstraction used by OpenHands/Aider style model strings; not a wire protocol by itself. |
| `ollama` | Native Ollama API or OpenAI shim | Usually none/local | Prefer native only when provider has a dedicated Ollama connector. |
| `native-vendor` | Provider's own account/login path | Vendor account or CLI login | Claude Code, Gemini CLI, Copilot; model selection only, not generic local endpoint propagation. |

## Capability matrix

| Provider | Custom endpoint | Config mechanism | Current repo signal | Reconcile/projection unit | Support status | Priority | Review stance |
|---|---:|---|---|---|---|---:|---|
| `pi` | Yes | structured JSON | Harness template has `providers.<id>.models[]` | provider block + model list | auto after MO06 | P1 | Good structured adapter candidate. |
| `opencode` | Yes | structured JSON | Descriptor uses `.opencode/opencode.json`; harness writes `.opencode/config.json` | provider block + models map | blocked until path/container unified | P1 | Validation gate before writer. |
| `local-openai` | Yes | AG catalog | Catalog output currently violates schema | catalog entry/alias | auto after MO05 | P1 | First bug fix. |
| `openhands` | Yes | structured TOML candidate (`.openhands/config.toml` `[llm]`) + env projection | Repo manages `.openhands/config.toml` for MCP | `[llm]` section (single active model) or launch env | auto after `[llm]` validation; env fallback | P1 | Structured-file preferred; env stays the key-injection vehicle. |
| `goose` | Yes, upstream likely supports multiple providers | repo currently has `.goose/config.yaml` MCP and stub execution | no confirmed model-config writer | ⟨FILL⟩ | blocked/validate-first | P1/P2 | Remove JSON assumption. Confirm path/schema first. |
| `codex` | Limited/custom | project TOML preferred; user-global fallback | Repo manages project `.codex/config.toml` (MCP/LSP) | `model_providers` table + active model | auto if project scope honored; consent-gated user-global otherwise | P1 | Verify project-scope `model_providers` first (MO09). |
| `qwen` | Yes | structured JSON | No writer yet | `modelProviders` entries | auto after schema/path validation | P1 | Merge/collision risk. |
| `continue` | Yes | incumbent `.continue/config.json` first; YAML only if installed version requires | Repo manages `.continue/config.json` for MCP | `models[]` entries | auto after adapter validation | P2 | Same-file rule: MCP + models never split across files. |
| `cline` | Yes | VS Code extension storage | No stable storage adapter | manual profile | manual/blocked | P2 | Host-adapter validation required. |
| `roo` | Yes | VS Code extension storage | Descriptor currently says `access_mode: env`, which is misleading for extension profile state | manual profile | manual/blocked | P2 | Fix descriptor semantics before model adapter. |
| `aider` | Yes | env projection first | execution adapter currently not a real launch target | launch env + model flag | manual → auto env when execution exists | P2 | No persistent file writer until `.aider.conf.yml` merge behavior verified. |
| `plandex` | Yes | structured custom model config | adapter/path not wired | provider + model + pack | blocked | P2 | Implement after path/schema discovery. |
| `gemini` | Native/account primarily | vendor CLI/account | no generic endpoint writer | native model id only | unsupported for arbitrary local endpoint | P3 | Exclude from generic projection. |
| `claude` | Native/gateway primarily | vendor CLI/account/env | no generic endpoint writer | native/gateway recipe only | unsupported for OpenAI-compatible local endpoint | P3 | Separate gateway recipe if needed. |
| `copilot` | No generic | account service | account-derived | N/A | unsupported | N/A | Not a target. |
| `antigravity` | Not validated | managed-agent/API research | no provider adapter | N/A | research-only | N/A | Not part of endpoint propagation. |

## Connector capability per provider

`⟨FILL⟩` means verify against installed upstream or repo adapter before enabling auto-projection.

| Provider | openai-compatible | anthropic | gemini | openrouter | ollama/local | Preferred projection |
|---|---:|---:|---:|---:|---:|---|
| `pi` | Yes (primary connector) | Yes via openai-completions adapter | Yes via openai-completions adapter (default provider name "google") | Yes via openai-compatible fallback | Yes via shim | Pi provider block with `api`/`compat` in `~/.pi/agent/models.json`. |
| `opencode` | Yes (native AI SDK) | Yes (native AI SDK, OAuth login required) | Yes (native AI SDK, API login required) | No — not a listed credential provider | Yes | Native AI SDK provider where available; fallback OpenAI-compatible for custom entries. |
| `local-openai` | Yes | No | No | via base URL only | Yes via OpenAI shim | AG OpenAI-compatible catalog. |
| `openhands` | Yes | Yes via LiteLLM | Yes via LiteLLM | Yes via LiteLLM | Yes | LiteLLM/OpenAI model prefixes through launch env. |
| `goose` | Yes | Yes | ⟨FILL⟩ | ⟨FILL⟩ | Yes | ⟨FILL: config path/schema/reload⟩. |
| `codex` | Yes via model_providers (chat wire_api) | Yes via model_providers if wire API matches | Yes via model_providers if wire API matches | Yes via model_providers openai-compatible | built-ins/compat only | `~/.codex/config.toml` or project `.codex/config.toml` [model_providers]; consent-gated for user-global writes. |
| `qwen` | Yes (dedicated CLI flags: `--openai-api-key`, `--openai-base-url`) | No native integration | No native integration | Via openai-compatible proxy — not tested | ⟨FILL⟩ | Single-model via `-m <id>` + openai-compatible connector; no multi-provider config surface. |
| `continue` | Yes | Yes | Yes | Yes | Yes | Continue provider type / YAML `models[]`. |
| `cline` | Yes | Yes | Yes | Yes | Yes | Manual extension profile. |
| `roo` | Yes | ⟨FILL⟩ | ⟨FILL⟩ | Yes | ⟨FILL⟩ | Manual extension profile until storage validated. |
| `aider` | Yes | Yes via LiteLLM | Yes via LiteLLM | Yes | Yes | Env + model prefix/flag. |
| `plandex` | Yes only for custom providers | No generic custom wire | No generic custom wire | As OpenAI-compatible only | If OpenAI-compatible | Custom model config after path discovery. |
| `gemini` | Gemini API can expose an OpenAI-compatible endpoint to other clients, but Gemini CLI as consumer is not validated | No | Yes | No | No | Native vendor. |
| `claude` | No generic OpenAI-compatible consumer path | Yes (primary) + 3P providers (Bedrock/Vertex/Foundry per help text) | No | Gateway only | No | Native vendor with 3P provider extension (enterprise routing through Bedrock, Vertex AI, Foundry — each uses its own credentials per help). |
| `copilot` | No | No | No | No | No | N/A. |
| `antigravity` | not supported [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) | not supported [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) | verified native (oauth-personal; antigravity v2.2.1 active, CLI `agy`) [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) | not supported [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) | Google account OAuth login only; no external vendor routing surface [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) | vendor set only (account tier determines models) [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) |

## Agent provider × vendor support matrix (running reference — MO09 deep dive)

Per (agent provider, upstream vendor/aggregator): projection mode, key mechanism, and whether the model set is all-or-nothing or per-model selectable. Every cell is a **verification target** — expected values below come from general product knowledge and MUST be confirmed against the installed tool version before any adapter relies on them (replace the `⟨FILL⟩` marker with the verified fact + source). "All models" means native enablement exposes the vendor's full set with no AG-side filtering; "selectable" means config carries explicit model entries so `model-filter` applies.

| Agent provider | OpenAI | Anthropic | Google | OpenRouter | Key mechanism (expected) | Model set granularity |
|---|---|---|---|---|---|---|
| `pi` | verified native env var [§pi-openai](model-source-evidence/pi.md#pi-openai) | verified native env var [§pi-anthropic](model-source-evidence/pi.md#pi-anthropic) | verified native env var (default provider) [§pi-google](model-source-evidence/pi.md#pi-google) | verified native env var [§pi-openrouter](model-source-evidence/pi.md#pi-openrouter) | env: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY` + CLI `--api-key`; custom endpoints via `~/.pi/agent/models.json` [§pi-evidence](model-source-evidence/pi.md#pi-evidence) | all models per vendor (native); selectable for custom entries [§pi-evidence](model-source-evidence/pi.md#pi-evidence) |
| `opencode` | verified native (OAuth; env path untested) [§opencode-openai](model-source-evidence/opencode.md#opencode-openai) | verified native (OAuth; env blocked by probe) [§opencode-anthropic](model-source-evidence/opencode.md#opencode-anthropic) | verified native (API login; env blocked by probe) [§opencode-google](model-source-evidence/opencode.md#opencode-google) | blocked: not a listed credential provider; custom-entries path unverified [§opencode-openrouter](model-source-evidence/opencode.md#opencode-openrouter) | OAuth/API login → `~\.local\share\opencode\auth.json`; standard env vars (`ANTHROPIC_API_KEY`/`GOOGLE_API_KEY`) confirmed NOT accepted; `OPENAI_API_KEY` path untested [§opencode-evidence](model-source-evidence/opencode.md#opencode-evidence) | all models per enabled vendor (OpenAI verified via catalog; Anthropic/Google expected pattern; config filename/container contract unresolved) [§opencode-evidence](model-source-evidence/opencode.md#opencode-evidence) |
| `openhands` | verified launch-env route [§openhands-openai](model-source-evidence/openhands.md#openhands-openai) | verified launch-env route [§openhands-anthropic](model-source-evidence/openhands.md#openhands-anthropic) | verified launch-env route [§openhands-google](model-source-evidence/openhands.md#openhands-google) | verified launch-env route [§openhands-openrouter](model-source-evidence/openhands.md#openhands-openrouter) | env: `LLM_API_KEY` + `LLM_MODEL=<prefix>/<id>` + `--override-with-envs`; `[llm]` config fallback (keys unverified vs installed v) [§openhands-evidence](model-source-evidence/openhands.md#openhands-evidence) | single model at a time [§openhands-evidence](model-source-evidence/openhands.md#openhands-evidence) |
| `goose` | native ⟨FILL⟩ | native ⟨FILL⟩ | ⟨FILL⟩ | native ⟨FILL⟩ | env keys via goose configure ⟨FILL⟩ | all models per vendor ⟨FILL⟩ |
| `codex` | verified native (vendor account, no key injection; v0.87.0) [§codex-openai](model-source-evidence/codex.md#codex-openai) | blocked: wire compat + project-scope unverified [§codex-anthropic](model-source-evidence/codex.md#codex-anthropic) | blocked: wire compat + project-scope unverified [§codex-google](model-source-evidence/codex.md#codex-google) | blocked: project-scope + execution unverified [§codex-openrouter](model-source-evidence/codex.md#codex-openrouter) | config: `~/.codex/config.toml` env_key refs; project `.codex/config.toml` managed by repo (project-scope precedence NOT verified) [§codex-evidence](model-source-evidence/codex.md#codex-evidence) | selectable (provider tables) [§codex-evidence](model-source-evidence/codex.md#codex-evidence) |
| `qwen` | verified native (auth-type: openai; v0.13.1) [§qwen-openai](model-source-evidence/qwen.md#qwen-openai) | verified native (auth-type: anthropic; key mechanism partially verified) [§qwen-anthropic](model-source-evidence/qwen.md#qwen-anthropic) | verified native (auth-type: gemini/vertex-ai; key mechanism blocked) [§qwen-google](model-source-evidence/qwen.md#qwen-google) | blocked: not a listed auth type; possible via openai-compatible proxy — not tested [§qwen-openrouter](model-source-evidence/qwen.md#qwen-openrouter) | multi-auth-type selection (`--auth-type`); per-type env var keys expected (exact names blocked without isolated test); `-m <model>`; settings `~/.qwen/settings.json` [§qwen-evidence](model-source-evidence/qwen.md#qwen-evidence) | single model at a time via `-m` or settings `"model.name"` [§qwen-evidence](model-source-evidence/qwen.md#qwen-evidence) |
| `continue` | custom-entries | custom-entries | custom-entries | custom-entries | config: per-model `apiKey` / env refs ⟨FILL⟩ | selectable (explicit `models[]`) |
| `cline` | native (UI profile) | native (UI profile) | native (UI profile) | native (UI profile) | extension storage — manual only | all models per selected provider |
| `roo` | native (UI profile) ⟨FILL⟩ | native ⟨FILL⟩ | native ⟨FILL⟩ | native ⟨FILL⟩ | extension storage — manual only | all models per selected provider ⟨FILL⟩ |
| `aider` | verified native via LiteLLM | verified native via LiteLLM | verified native via LiteLLM (gemini prefix) | verified native via LiteLLM (openrouter prefix) | env: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`; generic `--api-key PROVIDER=KEY` flag; model flag selects active | all models addressable; one active via flag |
| `plandex` | custom-entries ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ | as openai-compatible ⟨FILL⟩ | ⟨FILL⟩ | ⟨FILL⟩ |
| `gemini` | not supported [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) | not supported [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) | verified native (oauth-personal; gemini CLI deprecated, antigravity v2.2.1 active) [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) | not supported [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) | Google account OAuth login only; no external vendor routing surface [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) | vendor set only (account tier determines available models) [§gemini-evidence](model-source-evidence/gemini.md#gemini-evidence) |
| `claude` | not supported [§claude-evidence](model-source-evidence/claude.md#claude-evidence) | verified native (ANTHROPIC_API_KEY or OAuth/keychain; claude-code v2.1.199 active) [§claude-evidence](model-source-evidence/claude.md#claude-evidence) | not supported [§claude-evidence](model-source-evidence/claude.md#claude-evidence) | not supported — enterprise auth gateway only [§claude-evidence](model-source-evidence/claude.md#claude-evidence) | ANTHROPIC_API_KEY or OAuth/keychain login; `~/.claude/settings.json` with `"model"` field; no external vendor routing [§claude-evidence](model-source-evidence/claude.md#claude-evidence) | vendor set only (any Anthropic model via name alias) [§claude-evidence](model-source-evidence/claude.md#claude-evidence) |
| `copilot` | no | account-derived | account-derived | no | account service — not injectable | account set only |

Matrix discipline: MO09 verifies rows provider-by-provider (installed version, docs, and repo adapter code), replaces `⟨FILL⟩` cells, and records the source of each verified fact. A verified "native + env" cell unlocks key injection for that pair; a verified "custom-entries" cell unlocks filtered materialization; anything unverified stays manual.

## Per-provider adapter notes

### `pi`

- Repo-verified (2026-07-10) shape from `src/audiagentic/runtime/harness/pi/templates/home/agent/models.json` — note it is **home-scoped** (pi agent home dir, not project root), so model writes are user-home writes:

```json
{
  "providers": {
    "<source-id>": {
      "baseUrl": "http://127.0.0.1:1234/v1",
      "api": "openai-completions",
      "apiKey": "<resolved at write time>",
      "compat": {"supportsDeveloperRole": false, "supportsReasoningEffort": false},
      "models": [
        {"id": "<model-id>", "name": "<display-name>", "reasoning": false,
         "input": ["text"], "contextWindow": 262144, "maxTokens": 4096,
         "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}
      ]
    }
  }
}
```

- Materialization: one `providers.<source-id>` block per source; local-endpoint → one `models[]` entry; remote-account custom-entries → one entry per post-filter model. Reconcile by model `id` inside the AG-owned provider block; never touch other provider blocks.
- Still verify: whether a project-scope override exists, reload behavior, and non-openai `api` values (⟨FILL⟩).

### `opencode`

- Current repo conflict (re-confirmed 2026-07-10): descriptor MCP/LSP config points at `.opencode/opencode.json`, but the harness materializer (`_build_opencode_provider_config`) writes `.opencode/config.json` with top-level `providers`. Repo-verified harness shape:

```json
{
  "providers": {
    "<source-id>": {
      "name": "<source-id>", "api": "openai",
      "baseURL": "http://127.0.0.1:<port>/v1", "apiKey": "<key>",
      "models": {"<model-id>": {"contextWindow": 131072, "maxTokens": 4096, "cost": {"input": 0, "output": 0}}}
    }
  }
}
```

- Do not implement model writing until this is resolved atomically for MCP + LSP + model config; adapter must validate whether installed OpenCode expects `provider` or `providers` and which file wins (⟨FILL⟩ — MO09/MO03 gate).
- Materialization once unified: local-endpoint / custom-entries → `provider.<source-id>` block with a models map (note casing `baseURL` here vs Pi's `baseUrl`). Vendor via native key injection NOT viable for P1 vendors — OpenCode requires its own credential flow (`opencode providers login` → `~\.local\share\opencode\auth.json`) and does not accept standard env vars ([evidence](model-source-evidence/opencode.md#opencode-evidence)). Built-in credential vendor ids: openai (oauth), anthropic (oauth), google (api); openrouter NOT listed. Custom providers via `providers.<id>` entries using `@ai-sdk/openai-compatible` adapter are the only env-key-injection path and require structured config writes (gated by MO03).

### `local-openai`

- Fix catalog output first: map status to `active|deprecated|experimental`, provide positive integer context-window fallback, keep booleans boolean.
- This is a native AG catalog bridge; no external provider file is written.

### `openhands`

- Repo fact (2026-07-10): the descriptor manages `.openhands/config.toml` for MCP — NOT `settings.json` (the earlier settings.json gate was aimed at a file the repo never touches). OpenHands' `config.toml` carries a structured `[llm]` section, which would make this a **structured-file adapter over the TOML surface we already write**:

```toml
[llm]
model = "openai/<model-id>"        # LiteLLM prefix convention
base_url = "http://127.0.0.1:1234/v1"
api_key = "<env-ref resolution — verify OpenHands env interpolation support>"
```

- Validation gate (re-aimed): verify `[llm]` section semantics/keys in the installed OpenHands version (⟨FILL⟩ — MO09). If confirmed, structured-file is preferred; env projection (`LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY`) remains the fallback and the launch-time key-injection vehicle.
- Single-active-model semantics either way: OpenHands binds one `[llm]` at a time, so "enable a vendor" means selecting one model, not materializing a set.

### `goose`

- Current repo has `.goose/config.yaml` for MCP and execution is a stub. The prior JSON custom-provider assumption is not valid against current code.
- Treat model config as validate-first: confirm Goose provider config path, format, keys, reload behavior, and whether model config belongs in `.goose/config.yaml`, user config, or env.
- If no safe file contract is available, use env/config guidance and `NoAutomationRecipe` rather than fragments.

### `codex`

- Repo fact (2026-07-10): the descriptor ALREADY manages **project-scoped** `.codex/config.toml` for MCP (`remote: false`, codex-toml format) and LSP. Preferred path: verify whether the installed Codex honors `model_providers` in project `.codex/config.toml`; if yes, model config rides the same project TOML writer with no consent machinery. User-global `~/.codex/config.toml` becomes the consent-gated + dry-run FALLBACK only if project scope is ignored (⟨FILL⟩ — MO09 verification).
- Expected materialization (TOML):

```toml
[model_providers.<source-id>]
name = "<display-name>"
base_url = "http://127.0.0.1:1234/v1"
env_key = "AUDIAGENTIC_LOCAL_API_KEY"   # env-key reference, never inline secrets
wire_api = "chat"                        # validate: responses-only servers may not work

model = "<model-id>"                     # active model selection
model_provider = "<source-id>"
```

- Adapter must validate required `wire_api` compatibility; chat-completions-only local servers may not be enough. Vendor path: OpenAI is Codex's native account (no injection needed); other vendors only via `model_providers` if the wire API matches.

### `qwen`

- Target `modelProviders` only after settings path/scope and merge/replacement behavior are verified.
- Add collisions tests for unmanaged entries and duplicate visible ids.

### `continue`

- Repo fact (2026-07-10): the descriptor already manages `.continue/config.json` (JSON) for MCP — that file is the incumbent surface. INVERTED ordering vs earlier plan: extend `config.json` with `models[]` first (same file, same writer conventions); adopt the newer YAML config only if the installed Continue version requires it (⟨FILL⟩ — MO09), and then migrate MCP + models atomically per §10. Never manage the two kinds in different files.
- Expected materialization (JSON `models[]` entry): `{"title": "<display-name>", "provider": "openai", "model": "<model-id>", "apiBase": "http://127.0.0.1:1234/v1", "apiKey": "<resolved>"}` — vendor sources use Continue's native provider types (`anthropic`, `gemini`, `openrouter`) per entry.
- Preserve roles/capabilities and unmanaged models; do not assume a single global active model pointer because Continue supports role-based model selection.

### `cline` and `roo`

- Capability exists, but automation is blocked by extension-storage/profile uncertainty.
- Use host adapter if storage access is ever automated; do not hard-code VS Code global/workspace storage paths.
- Roo descriptor semantics should be fixed before model work; `access_mode: env` currently implies `auth-ref` behavior that does not match extension-managed profile state.

### `aider`

- Env projection and CLI model flag first, once execution adapter is a real launch target.
- `.aider.conf.yml` writer remains blocked until merge/removal behavior is validated.

### `plandex`

- Custom providers are OpenAI-compatible, but adapter path/schema must be discovered first.
- Confirm model pack behavior, unique provider/model ids, and config scope before writing.

### `gemini`, `claude`, `copilot`, `antigravity`

- Keep out of generic local endpoint propagation.
- Gemini/Claude may later get native model-selection or gateway recipes, but those are not OpenAI-compatible local endpoint adapters.
- Copilot is account/service-derived.
- Antigravity is managed-agent research, not endpoint projection.

## Implementation requirements

### Descriptor metadata

Implemented (MO01): the model kind reuses the same top-level-sibling pattern as `mcp_config`/`language_servers_config` — a `ManagedConfigSpec` field (added when MO02 lands the model-endpoint desired-entry builder) plus two provider-YAML-declared capability fields on `ProviderDescriptor`, both empty by default (an undeclared pair projects nothing — never guessed):

```yaml
# per-provider config/providers/<id>.yaml
model_config:                    # MO02: ManagedConfigSpec for this provider's
  config_path: ".opencode/config.json"   # model-endpoint config surface
  reader: "...:read_opencode_models"
  writer: "...:write_opencode_models"
  remover: "...:remove_opencode_models"
  format: "opencode-json"
  refresh_mode: "file-watch"

supported_connectors:             # MO01, implemented: custom-entries projection path
  - openai-compatible
  - openrouter

vendor_key_injection:             # MO01, implemented: native-key-injection path
  anthropic:
    mechanism: env
    key: ANTHROPIC_API_KEY
```

No `managed_configs:` nesting — do not introduce a third long-lived `*ConfigSpec` clone; the model kind's `ManagedConfigSpec` is a sibling field to `mcp_config`/`language_servers_config`, same as those two.

### Service shape

Expose model operations as thin bindings over the generalized sync/reload core:

- `sync_managed_provider_models(provider_id, project_root, desired_entries)`
- `sync_managed_provider_models_subset(..., managed_ids={...})`
- `list_provider_models_config(provider_id, project_root)`
- `reload_provider_models(provider_id, project_root)`

Use:

- `reconcile_fragments` + `FragmentStore` for structured entries.
- One generalized `ManagedFragmentRegistry` instance for `.audiagentic/runtime/providers/managed-model-endpoints.json`.
- A model-specific `ProviderRecipeKind` for lifecycle/status/dry-run.
- `NoAutomationRecipe` for manual/unsupported/blocked providers.
- A dedicated launch-env contribution recipe for env-projection providers.
- A sibling `_sync_provider_models` call inside `reconcile.py::reconcile_provider`.
- Provider status fields for support mode, config path, managed count, refresh mode, collisions, last sync, and action-needed.

MCP tool surface (ag-providers server, exposed only after service tests are green — names are pinned here so they cannot drift or collide with the existing catalog tools). Two groups, mirroring the split the repo already uses for languages (`lsp_manage_mcp.py`: `lsp_add_language`/`lsp_remove_language`/`lsp_set_language_option`/`lsp_list_languages`):

**Source management (mutate desired state — `.audiagentic/config/model-sources.yaml` — never provider config files directly; that stays the reconciler's job, same invariant as recipes). Every mutation validates against `model-sources.schema.json` before writing and supports `apply: bool = True` (reconcile after write) and `dry_run`:**

- `model_source_list()` — sources with class, grouping, connector, discovery, enabled, per-provider projection modes, materialized-model counts.
- `model_source_add(source_id, config)` — add a local endpoint or remote account (full config dict per the schema).
- `model_source_update(source_id, updates)` — change endpoint fields, key-ref, `model-filter`, provider-overrides.
- `model_source_remove(source_id)` — delete the source; reconcile removes only AG-owned projections.
- `model_source_set_enabled(source_id, enabled)` — disable/enable without deleting configuration.

Per-model granularity maps through the taxonomy rather than extra tools: `local-endpoint` is one source per model, so set_enabled/remove IS per-model control; `remote-account` via custom-entries uses `model-filter` edits (`model_source_update`); `remote-account` via key injection is source-level all-or-nothing (the agent owns the model list — status reports this, tools must not pretend otherwise).

**Projection/sync operations (per agent provider):**

- `sync_provider_models(provider_id, dry_run=False, managed_ids=None)` — wraps `sync_managed_provider_models(_subset)`.
- `list_provider_models_config(provider_id)` — the MANAGED config view; distinct from the existing `list_provider_models`, which reports the runtime catalog.
- `reload_provider_models(provider_id)` — refresh-mode-aware reload or action-needed text.
- Existing tools unchanged: `list_provider_models`, `refresh_provider_catalog`, `refresh_all_catalogs` stay catalog-side; `reconcile_provider` gains model sync internally (MO02 step 6), not a new signature.

Direct edits to `model-sources.yaml` remain first-class (the tools and humans write the same file); the tools add validation, status feedback, and reconcile-on-write.

Do not:

- Clone `services/mcp.py` into a second full model service.
- Add a third persistent `*ConfigSpec` dataclass.
- Add a second hard-coded registry module.
- Write provider model config directly from recipes.
- Use text block patching for JSON/TOML/YAML entries.
- Force env-projection or extension-storage through `reconcile_fragments`.
- Treat unsupported vendor/account catalogs as custom endpoint allowlists.

## Review gates

| Gate | Required evidence |
|---|---|
| MO05 catalog gate | `local-openai` catalog payload validates against `provider-model-catalog.schema.json`. |
| MO06 shared-core gate | MCP and LSP tests pass unchanged through the generalized managed-config core. |
| Endpoint schema gate | `model-sources` schema validates both source classes, multiple endpoints, connector-specific fields, provider overrides, and secret refs. |
| Source enablement gate | Enabling a remote-account source projects per the verified (provider, vendor) mode — key injection or filtered custom entries — and disabling removes only owned entries/env contributions; catalog-refresh failure degrades to cached + `action_needed`, never a sync failure. |
| Key injection gate | Injected keys come only from `api-key-ref` resolution at write/launch time; no key value ever lands in registries, status output, timelines, or logs; config-mechanism injection is dry-runnable. |
| Structured adapter gate | First OpenCode/Pi writer preserves unmanaged entries, removes only owned entries, and reports collisions. |
| Env projection gate | OpenHands/Aider launch env receives endpoint-derived values without registry fragments or secret logging. |
| Consent gate | Codex dry-run and apply require explicit user-global write consent. |
| Manual/blocked gate | Cline/Roo/Plandex/unsupported providers report guidance-only status with action-needed text. |
| Documentation gate | This reference is updated whenever any `⟨FILL⟩` field becomes verified, a new model source is enabled, or a provider's support status changes. This document is the single authoritative capability matrix — provider READMEs link here and never duplicate it. |

## First implementation order

1. Fix `local-openai` catalog validation.
2. Consolidate `ManagedConfigSpec`, `ManagedFragmentRegistry`, and `sync_managed_config` so MCP/LSP/model config share one implementation.
3. Add `model-endpoints` project schema and tests for connector taxonomy and multiple local models.
4. Resolve OpenCode config path/container mismatch before any OpenCode writer.
5. Implement Pi structured adapter.
6. Implement OpenHands env-projection capability recipe.
7. Implement Codex with consent-gated user-global TOML writes.
8. Implement Qwen after path/merge validation.
9. Reassess Goose after path/schema validation; do not assume JSON.
10. Implement Continue YAML adapter.
11. Keep Cline/Roo/Plandex blocked/manual until storage/path validation is done.

## Open verification list

| Provider | Verification blocker |
|---|---|
| `pi` | Project/home scope, active/default model selection, reload behavior. |
| `opencode` | `.opencode/config.json` vs `.opencode/opencode.json`, `providers` vs `provider`, active model pointer. |
| `openhands` | Settings file schema and safe managed-write scope. |
| `goose` | Provider model config path/format/schema/reload behavior; current repo only confirms `.goose/config.yaml` MCP. |
| `codex` | Required wire API and restart/reload behavior. |
| `qwen` | Settings path, selection semantics, merge/replacement behavior. |
| `continue` | Config path/version and file-watch behavior. |
| `cline` | Extension storage format/profile scope. |
| `roo` | Descriptor access-mode semantics, extension storage format/profile scope, tool-calling constraints. |
| `aider` | Real execution launch seam and `.aider.conf.yml` merge behavior. |
| `plandex` | Custom model config path/scope/schema. |
| `gemini` / `claude` | Only vendor/gateway recipes unless a generic custom-endpoint consumer path is validated. |
