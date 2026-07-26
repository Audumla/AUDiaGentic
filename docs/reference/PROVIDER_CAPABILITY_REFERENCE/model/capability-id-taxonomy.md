# Canonical Capability ID Mapping

**Authority:** MA19. This document maps architectural capability families from
[../model/capability-operation-contract.md](../model/capability-operation-contract.md) and descriptor
operational declarations to stable `capability_id` values for `capability_facts`.

Providers use these IDs when a capability claim needs durable provenance,
constraints, uncertainty, or verification history. Facts are a curated evidence
catalogue, not a required mirror of every operational descriptor field. The
descriptor remains authoritative for runtime behavior, and the absence of an
evidence fact does not negate a declared operational capability.

## Capability ID taxonomy

IDs use the `<domain>-<operation>` pattern. This table is a **closed
catalogue**: the capability-id namespace is closed per PC01 (VAL-PCAP-009 —
reverses the original MA19/MA20 open policy). A new kind requires updating
this document and the catalogue YAML; no ad-hoc IDs are accepted. Tier values
within a kind's mechanism enum are open-ended and grow as providers are
investigated (e.g. `execution-isolation` tiers: full/partial/no + more as
discovered). Domain prefixes:

| Prefix | Domain | CAPABILITY_OPERATION_SCHEMA family |
| --- | --- | --- |
| `cli-*` | CLI provisioning | Automation family: CLI desired state |
| `mcp-*` | MCP configuration | Automation family: Managed MCP entries |
| `lsp-*` | LSP projection | Automation family: Language-server (consolidated from 2 families) |
| `model-*` | Model catalog, config, connectors | Automation family: Model projection + Query: catalog reads |
| `surface-*` | Surface rendering | Automation family: Generated provider surfaces |
| `exec-*` | Execution isolation / adaptation | Operational tier declarations (execution-isolation, launch-isolation, exec-adapter) |
| `hook-*` | Hooks and rules | Automation family: Rules/hooks |
| `provider-*` | Provider-specific configuration | Automation family: Provider-specific configuration |
| `plugin-*` | Plugin configuration | Automation family: Plugin configuration |
| `ext-*` | Host/editor extensions | Operational declaration — kind name is `host-extension` (not ext-declaration) |
| `obs-*` | Harness observability signals | Evidence for the AS19 descriptor observability declaration (RV560); never enables projection by itself |
| `acp-*` | ACP transport/session facts | Evidence only (see protocols/acp-capabilities.md); execution authority stays with adapter registration |
| `perm-*` | Permissions | Operational declaration (not automation) |
| `file-*` | Agent files | Operational declaration (not automation) |
| `depr-*` | Deprecation | Operational declaration (not automation) |

## Capability ID definitions

Each kind includes its **authority** (automation = produces ProviderAutomationCapability, operational = harness reads it for decisions, evidence-only = inert record), **cardinality** (single = one value, list = multiple entries per provider), and **mechanism_schema** (what shape the mechanism field takes).

### Automation kinds (produce ProviderAutomationCapability)

These reconcile against a FamilyPin in code. The family_id links the catalogue entry to its owning family module.

#### `cli-install` — CLI installation automation

- **Authority:** automation | **Cardinality:** single | **Family:** cli-lifecycle | **Mechanism:** cli-install-recipe
- Provider can be installed from the harness via a known install command (uv, npm, curl) plus a version probe.
- Inner mechanism field `probe_fn` / `cli_probe` declares how the installed binary is verified. Not a separate kind — it's a modifier inside this one.

#### `mcp-config` — MCP config management automation

- **Authority:** automation | **Cardinality:** single | **Family:** managed-mcp | **Mechanism:** managed-config-spec
- Provider has a manageable MCP server config file with reader/writer/remover operations (e.g. ~/.claude/mcp.json, .opencode/opencode.json).
- Inner mechanism field `capabilities: [remote]` declares whether remote (non-stdio) entries are supported. Not a separate kind — it's a modifier inside this one.

#### `model-catalog-refresh` — Live model catalog fetch

- **Authority:** automation | **Cardinality:** single | **Family:** model-projection | **Mechanism:** callable-ref
- Provider can fetch a live list of available models via a callable (e.g. `_fetch_claude_catalog`). Returns current model list for the provider's endpoint.

#### `model-config` — Model config management automation

- **Authority:** automation | **Cardinality:** single | **Family:** model-projection | **Mechanism:** managed-config-spec
- Provider has a manageable model configuration surface with reader/writer/remover over a known config path. Shares the model-projection family with model-catalog-refresh.

#### `surface-render` — Surface rendering automation

- **Authority:** automation | **Cardinality:** single | **Family:** generated-surfaces | **Mechanism:** surfaces-struct
- Provider supports rendering provider surfaces (skills + instructions) via a renderer. The mechanism declares `{renderer: "flat-skill"|"none", contribution-file: "AGENTS.md"}`. Providers with `renderer: none` can still contribute to instruction files but cannot auto-render skills.

#### `lsp-automation` — LSP automation (consolidated from 2 families)

- **Authority:** automation | **Cardinality:** single | **Family:** language-server | **Mechanism:** lsp-automation-spec
- **Replaces `lsp-config` + `lsp-self-support`.** These were two separate families with different contracts — but they're the same family with different implementations. One kind, one FamilyPin, full modes [plan, apply, prune, status]. The mechanism declares `{approach: "hook"|"config"|"mcp-fallback", ...}` to distinguish how the provider manages LSP:
  - `approach: "config"` — provider has a manageable LSP config surface (reader/writer/remover over a config file). Formerly lsp-config.
  - `approach: "hook"` — provider self-provides LSP via a callable hook that installs support. Formerly lsp-self-support. Prune = uninstall the hook, not just remove config entries.
  - `approach: "mcp-fallback"` — LSP managed via MCP server (future pattern).

#### `plugin-config` — Plugin configuration automation

- **Authority:** automation | **Cardinality:** single | **Family:** plugin-entry | **Mechanism:** managed-config-spec
- Provider has a manageable plugin config with reader/writer/remover over a known path (e.g. .opencode/opencode.json plugin array).

### Operational kinds (harness reads for decisions)

No FamilyPin — the harness consumes these directly to make routing/contention/scheduling decisions.

#### `perm-declaration` — Permissions declaration

- **Authority:** operational | **Cardinality:** single | **Mechanism:** permissions-struct
- Provider declares its permission surface via ProviderPermissions boolean flags (write_files, execute_shell, browse_web, read_env).

#### `host-extension` — Host/editor extension declaration

- **Authority:** operational | **Cardinality:** list | **Mechanism:** host-capability
- Provider declares host/editor extensions it requires or uses. Each entry is a VS Code extension ID (e.g. `anthropic.claude-code`, `GitHub.copilot`). List cardinality — a provider may declare multiple extensions. Evidence can be member-scoped per entry.

#### `surface-skill` — Skill surface path declaration

- **Authority:** operational | **Cardinality:** single | **Mechanism:** callable-ref
- Provider has a dedicated skill folder path (e.g. `.claude/skills/{tag}/SKILL.md`). This is where skills are contributed for this provider. Separate from surface-render — a provider can have a skill path without having a renderer.

#### `surface-instruction` — Instruction file declaration

- **Authority:** operational | **Cardinality:** single | **Mechanism:** boolean-set
- Provider has an instruction file in the project root (e.g. CLAUDE.md, AGENTS.md). The harness contributes managed content to this file. Separate from surface-render — a provider can have an instruction file without having a renderer.

#### `execution-isolation` — Execution isolation tier

- **Authority:** operational | **Cardinality:** single | **Mechanism:** tier-enum
- Provider's execution isolation level determines resource allocation and contention routing. The harness uses this to decide whether the provider can be used as an AG agent or needs contention limits:
  - `full-isolation` — exclusive local compute (e.g. one rig); resource key = `local-exclusive:{provider_id}`
  - `partial-isolation` — partial exclusive access; same resource key as full but with contention controls
  - `no-isolation` — shared CLI access; resource key = `cli:{provider_id}`, contention management applies
- **Tiers are open-ended** — new values added to the Literal enum as providers are investigated. Current tiers may be misclassified (e.g. claude has --mcp-config + --strict-mcp-config, suggesting it IS isolatable).
- Orthogonal field `execution_isolation_tier` remains on ProviderDescriptor for runtime access; this fact provides evidence and catalogue validation.

#### `launch-isolation` — MCP launch isolation tier

- **Authority:** operational | **Cardinality:** single | **Mechanism:** tier-enum
- **Renamed from `mcp-launch-isolation`.** Can the provider launch MCP servers in isolation (only caller's curated entries, no user global config)? This is NOT about whether the provider supports MCP — ALL providers have mcp-config. It's about whether we can inject MCP servers with isolation guarantees:
  - `exact` — exclusively isolated launch surface; only our curated MCP servers are loaded (e.g. opencode via OPENCODE_CONFIG_CONTENT + isolated XDG, pi via --mcp-exclusive)
  - `additive` — our servers launched but added on top of user's global config (fallback when exact isolation fails, e.g. pi's additive-fallback when exclusive patch cannot apply)
  - `unsupported` — no mechanism to reliably inject MCP servers with isolation; may still have mcp-config automation for managing the provider's config file
- **Tiers are open-ended** — new values added as providers are investigated. Current tier reflects implementation status (whether a surface builder exists), not just provider capability (claude supports --mcp-config + --strict-mcp-config but currently "unsupported" because no surface builder has been written).
- Orthogonal field `mcp_launch_isolation_tier` remains on ProviderDescriptor for runtime access; this fact provides evidence and catalogue validation.

#### `exec-adapter` — Execution adapter tier claim

- **Authority:** operational | **Cardinality:** single | **Mechanism:** tier-enum
- Provider declares its execution adapter mode. This is NOT automation — it's just a tier claim with no ProviderAutomationCapability. Values: `cli` (executable available), `stub` (adapter registered, bridge not wired), `ok-stub` (adapter registered but not fully tested), `unsupported`.

#### `model-connectors` — Model connector support declaration

- **Authority:** operational | **Cardinality:** single | **Mechanism:** boolean-set
- Provider supports specific model connectors (e.g. openai-compatible). Declared as a tuple of connector IDs.

#### `lsp-mcp-receive` — LSP MCP server receiver flag

- **Authority:** operational | **Cardinality:** single | **Mechanism:** boolean-set
- Provider can receive the ag-lsp MCP server. Default True; set to False to opt-out. Standalone operational flag with no parent mechanism.

#### `depr-status` — Deprecation status declaration

- **Authority:** operational | **Cardinality:** single | **Mechanism:** none
- Provider is deprecated (boolean). The `deprecated` field is NOT serialized by describe_provider — must read via get_descriptor directly.

### Evidence-only kinds (inert records)

No mechanism, no automation. These are claims about what is known about the provider, with constraints/limitations/action_needed tracking verification maturity.

#### `acp-support` — ACP capability declaration (consolidated from 4 kinds)

- **Authority:** evidence-only | **Cardinality:** single | **Mechanism:** acp-caps-list
- **Replaces 4 separate kinds** (`acp-stdio-transport`, `acp-live-session`, `acp-session-resume`, `acp-shared-live-session`). ACP capabilities are one concept with multiple sub-features — one fact per provider, mechanism = `{transports: [stdio], session_modes: [live, resume], shared: false}`. Sub-capabilities that are blocked/unimplemented are listed but marked as such in constraints/limitations.

#### `model-local-state` — Model local state declaration

- **Authority:** evidence-only | **Cardinality:** single | **Mechanism:** none
- **Renamed from `model-config-surface`.** Provider has a local model config file/state directory (e.g. ~/.cline/, ~/.codex/config.toml). This is LOCAL STATE, not a configurable surface like mcp_config. Evidence-only because the harness cannot automate against it — it just records what's known.

#### `model-credentials` — Model credentials mechanism declaration

- **Authority:** evidence-only | **Cardinality:** single | **Mechanism:** none
- **Renamed from `vendor-key-injection`.** Provider injects model vendor API keys via various mechanisms (env vars, CLI commands, auth flows). Evidence-only because the harness cannot automate against it — it just records what's known about how credentials work.

#### `model-config-projection` — Model config projection (blocked discovery)

- **Authority:** evidence-only | **Cardinality:** single | **Mechanism:** none
- Provider could potentially have model config projected into its native file, but the mechanism is unresolved. Currently blocked on opencode (config.json vs opencode.json container shape). Evidence-only with action_needed tracking.

#### `obs-*` — Harness observability claims (pattern)

- **Authority:** evidence-only | **Cardinality:** single | **Mechanism:** none
- **Renamed domain prefix from `hinv-*`.** Claims about the HARNESS's ability to observe a provider's execution, NOT about the provider's own capabilities. E.g. `obs-opencode-acp` = "we can observe opencode ACP execution" (AS27 inventory). Subject is `external:harness-observability/<provider>-<transport>`.

## Provider capability matrix

This matrix records representative mappings used to establish the naming
convention. Provider descriptors are the source of truth for operational
capabilities; add a `capability_facts` entry only when a separate evidence claim
is useful. Do not duplicate a descriptor field merely to make this matrix
exhaustive.

### Pi

| Capability ID | Present | Subject value | Notes |
| --- | --- | --- | --- |
| `cli-install` | Yes | `cli_install` | pi-harness with callable install/uninstall |
| `mcp-config` | Yes | `mcp_config` | .mcp.json, mcp-json format, restart-required |
| `lsp-automation` | Yes | `language_servers_config` + `on_lsp_enabled` | approach: "hook" via _pi_ensure_lens; also has lsp-config capability (approach: "config") — consolidated under one kind |
| `launch-isolation` | Yes | `mcp_launch_isolation_tier` | exact — pi-mcp-exclusive-patch with --no-extensions |
| `execution-isolation` | Yes | `execution_isolation_tier` | full-isolation |
| `perm-declaration` | Yes | `permissions` | write_files, execute_shell, read_env |
| `file-agent` | Yes | `agent_files` | .pi dir (unmanaged) |

### OpenCode

| Capability ID | Present | Subject value | Notes |
| --- | --- | --- | --- |
| `cli-install` | Yes | `cli_install` | uv install |
| `mcp-config` | Yes | `mcp_config` | .opencode/opencode.json, opencode-json format |
| `lsp-automation` | Yes | `language_servers_config` | approach: "config" via reader/writer/remover |
| `model-catalog-refresh` | Yes | `fetch_catalog_fn` | opencode models --verbose |
| `surface-render` | Yes | `surfaces` | flat-skill, CLAUDE.md |
| `surface-skill` | Yes | `skill_surface_path` | .claude/skills/{tag}/SKILL.md |
| `surface-instruction` | Yes | `instruction_file` | CLAUDE.md |
| `launch-isolation` | Yes | `mcp_launch_isolation_tier` | exact — OPENCODE_CONFIG_CONTENT + isolated XDG |
| `execution-isolation` | Yes | `execution_isolation_tier` | full-isolation |
| `exec-adapter` | Yes | `execution` | mode: cli |
| `plugin-config` | Yes | `plugin_config` | .opencode/opencode.json plugin array |
| `perm-declaration` | Yes | `permissions` | write_files, execute_shell, browse_web, read_env |
| `file-agent` | Yes | `agent_files` | CLAUDE.md (managed), .claude/ (unmanaged) |
| `model-local-state` | Yes | `external:model-config-projection` | Blocked: config path unresolved (config.json vs opencode.json) — evidence-only |

### Copilot

| Capability ID | Present | Subject value | Notes |
| --- | --- | --- | --- |
| `cli-install` | Yes | `cli_install` | npm: @github/copilot |
| `host-extension` | Yes | `host_capabilities` | GitHub.copilot, GitHub.copilot-chat (vscode) |
| `mcp-config` | Yes | `mcp_config` | .mcp.json, mcp-json format |
| `surface-render` | Yes | `surfaces` | flat-skill, COPILOT.md |
| `surface-instruction` | Yes | `instruction_file` | COPILOT.md |
| `execution-isolation` | Yes | `execution_isolation_tier` | no-isolation — shared CLI access |
| `exec-adapter` | Yes | `execution` | mode: cli |
| `perm-declaration` | Yes | `permissions` | no write/execute/browse/env |
| `file-agent` | Yes | `agent_files` | COPILOT.md (managed), .github/copilot-instructions.md (unmanaged) |

### Aider

| Capability ID | Present | Subject value | Notes |
| --- | --- | --- | --- |
| `cli-install` | Yes | `cli_install` | uv: aider-chat@latest |
| `execution-isolation` | Yes | `execution_isolation_tier` | partial-isolation — may need refinement |
| `exec-adapter` | Yes | `execution` | mode: stub |
| `perm-declaration` | Yes | `permissions` | write_files, execute_shell, browse_web, read_env |
| `file-agent` | Yes | `agent_files` | AGENTS.md, .aider.conf.yml (both unmanaged) |

### Gemini

| Capability ID | Present | Subject value | Notes |
| --- | --- | --- | --- |
| `cli-install` | Yes | `cli_install` | npm: @google/gemini-cli |
| `host-extension` | Yes | `host_capabilities` | google.gemini-cli-vscode-ide-companion (vscode) |
| `mcp-config` | Yes | `mcp_config` | .gemini/settings.json, mcp-json format |
| `surface-render` | Yes | `surfaces` | flat-skill, GEMINI.md |
| `surface-skill` | Yes | `skill_surface_path` | .gemini/commands/{tag}.md |
| `surface-instruction` | Yes | `instruction_file` | GEMINI.md |
| `depr-status` | Yes | `deprecated` | True, replaced by antigravity — boolean only, NOT serialized by describe_provider |
| `execution-isolation` | Yes | `execution_isolation_tier` | no-isolation — may need refinement (gemini CLI could be isolatable) |
| `perm-declaration` | Yes | `permissions` | write_files, execute_shell, browse_web, read_env |
| `file-agent` | Yes | `agent_files` | GEMINI.md (unmanaged) |

## Population strategy

When an evidence fact is useful:

1. **Verified facts** — for capabilities where the descriptor field is present and the mechanism is known (evidence_tier: `installed-artifact` or `execution`, review_state: `verified`). Subject resolves to the descriptor field name.
2. **Documentation facts** — for capabilities documented in evidence files but not yet verified against installed tool (evidence_tier: `documentation`, review_state: `pending-review`).
3. **Blocked/unverified facts** — for capabilities where the mechanism is uncertain or unresolved (evidence_tier: `unverified`, support_assessment: `blocked`).
4. **Omitted** — when the operational descriptor already carries the complete
   claim and no separate provenance, constraint, uncertainty, or verification
   history is useful. Do not create negative facts unless there is a specific
   gap or concern.

## Evidence source mapping

| Source | Path | Use for |
| --- | --- | --- |
| Provider YAML | `config/providers/<id>.yaml` | Verified facts from descriptor fields (installed-artifact tier) |
| Evidence docs | `harnesses/profiles/<id>.md` | Model-related capabilities (catalog, connectors, vendor injection) |
| Capability matrix | `endpoints/provider-model-endpoints.md` | Cross-reference for model connector support, projection modes |

## Subject resolution

The `subject` field references the descriptor field that provides the capability:

- Simple field: `mcp_config`, `permissions`, `execution` — subject is the field name
- Field member: `host_capabilities[google.gemini-cli-vscode-ide-companion]` — specific host capability
- External reference: `external:model-config-projection` — cross-provider or unresolved reference

## Fact anchor convention

The `fact_anchor` in evidence uses the format:

- Descriptor field: `config/providers/<id>.yaml#<field-name>`
- Evidence doc: `harnesses/profiles/<id>.md#<section>`
- Capability matrix: `endpoints/provider-model-endpoints.md#<provider>`
