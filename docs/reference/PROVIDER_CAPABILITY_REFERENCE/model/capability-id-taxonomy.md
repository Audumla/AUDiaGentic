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

IDs use the `<domain>-<operation>` pattern. This table is a **naming
convention, not a closed enum**: the capability-id namespace is open per
MA19/MA20 — a new evidence subject adds a row here, it does not require a
schema change, and no code may switch on this table. Domain prefixes:

| Prefix | Domain | CAPABILITY_OPERATION_SCHEMA family |
|---|---|---|
| `cli-*` | CLI provisioning | Automation family: CLI desired state |
| `mcp-*` | MCP configuration | Automation family: Managed MCP entries |
| `lsp-*` | LSP projection | Automation families: LSP projection, Generic LSP-MCP projection, Self-provided LSP support |
| `model-*` | Model catalog, config, connectors | Automation family: Model projection + Query: catalog reads |
| `surface-*` | Surface rendering | Automation family: Generated provider surfaces |
| `exec-*` | Agent execution | Agent execution (separate capability) |
| `hook-*` | Hooks and rules | Automation family: Rules/hooks |
| `provider-*` | Provider-specific configuration | Automation family: Provider-specific configuration |
| `plugin-*` | Plugin configuration | Automation family: Plugin configuration |
| `ext-*` | Host/editor extensions | Operational declaration (not automation) |
| `obs-*` | Harness observability signals | Evidence for the AS19 descriptor observability declaration (RV560); never enables projection by itself |
| `acp-*` | ACP transport/session facts | Evidence only (see protocols/acp-capabilities.md); execution authority stays with adapter registration |
| `perm-*` | Permissions | Operational declaration (not automation) |
| `file-*` | Agent files | Operational declaration (not automation) |
| `depr-*` | Deprecation | Operational declaration (not automation) |

## Capability ID definitions

### CLI & Provisioning

| Capability ID | Meaning | Descriptor field | Subject | Mechanism |
|---|---|---|---|---|
| `cli-probe` | Provider has a CLI probe mechanism | `cli_probe`, `probe_fn` | `cli_probe` | shell probe or callable probe_fn |
| `cli-install` | Provider can be installed | `cli_install` | `cli_install` | toolchain install step or callable |

### MCP

| Capability ID | Meaning | Descriptor field | Subject | Mechanism |
|---|---|---|---|---|
| `mcp-config` | Provider has MCP config surface | `mcp_config` | `mcp_config` | reader/writer/remover over config_path |
| `mcp-remote` | Provider MCP config supports remote entries | `mcp_config` capabilities | `mcp_config` | managed_config.REMOTE_CAPABILITY |

### LSP

| Capability ID | Meaning | Descriptor field | Subject | Mechanism |
|---|---|---|---|---|
| `lsp-config` | Provider has LSP config surface | `language_servers_config` | `language_servers_config` | reader/writer/remover over config_path |
| `lsp-self-support` | Provider self-provides LSP via hook | `on_lsp_enabled` | `on_lsp_enabled` | callable hook installs LSP support |
| `lsp-mcp-receive` | Provider receives ag-lsp MCP server | `receive_lsp_mcp` | `receive_lsp_mcp` | default True; False to opt-out |

### Model

| Capability ID | Meaning | Descriptor field | Subject | Mechanism |
|---|---|---|---|---|
| `model-catalog-refresh` | Provider can refresh model catalog | `fetch_catalog_fn` | `fetch_catalog_fn` | callable returning model list |
| `model-config` | Provider has model config surface | `model_config` | `model_config` | reader/writer/remover over config_path |
| `model-connectors` | Provider supports connectors | `supported_connectors` | `supported_connectors` | tuple of connector ids |
| `model-vendor-injection` | Provider supports vendor key injection | `vendor_key_injection` | `vendor_key_injection` | env or config mechanism per vendor |

### Surfaces

| Capability ID | Meaning | Descriptor field | Subject | Mechanism |
|---|---|---|---|---|
| `surface-render` | Provider supports surface rendering | `surfaces` | `surfaces` | renderer + contribution-file |
| `surface-skill` | Provider has skill surface path | `skill_surface_path` | `skill_surface_path` | path template with {tag} |
| `surface-instruction` | Provider has instruction file | `instruction_file` | `instruction_file` | managed file in project root |

### Execution

| Capability ID | Meaning | Descriptor field | Subject | Mechanism |
|---|---|---|---|---|
| `exec-adapter` | Provider has execution adapter | `execution` | `execution` | mode: cli/stub/ok-stub/unsupported |

### Hooks & Rules

| Capability ID | Meaning | Descriptor field | Subject | Mechanism |
|---|---|---|---|---|
| `hook-lsp-enabled` | Provider has on_lsp_enabled hook | `on_lsp_enabled` | `on_lsp_enabled` | callable hook on LSP enable |

### Extensions

| Capability ID | Meaning | Descriptor field | Subject | Mechanism |
|---|---|---|---|---|
| `ext-declaration` | Provider declares host/editor extensions | `host_capabilities` | `host_capabilities` | tuple of HostCapability |

### Permissions

| Capability ID | Meaning | Descriptor field | Subject | Mechanism |
|---|---|---|---|---|
| `perm-declaration` | Provider declares permissions | `permissions` | `permissions` | ProviderPermissions boolean flags |

### Agent Files

| Capability ID | Meaning | Descriptor field | Subject | Mechanism |
|---|---|---|---|---|
| `file-agent` | Provider declares agent files | `agent_files` | `agent_files` | tuple of AgentFile |

### Deprecation

| Capability ID | Meaning | Descriptor field | Subject | Mechanism |
|---|---|---|---|---|
| `depr-status` | Provider has deprecation status | `deprecated` | `deprecated` | boolean with annotations |

## Provider capability matrix

This matrix records representative mappings used to establish the naming
convention. Provider descriptors are the source of truth for operational
capabilities; add a `capability_facts` entry only when a separate evidence claim
is useful. Do not duplicate a descriptor field merely to make this matrix
exhaustive.

### Pi

| Capability ID | Present | Subject value | Notes |
|---|---|---|---|
| `cli-probe` | Yes | `cli_probe` | probe_fn: _pi_probe |
| `cli-install` | Yes | `cli_install` | pi-harness with callable install/uninstall |
| `mcp-config` | Yes | `mcp_config` | .mcp.json, mcp-json format, restart-required |
| `lsp-self-support` | Yes | `on_lsp_enabled` | _pi_ensure_lens hook |
| `hook-lsp-enabled` | Yes | `on_lsp_enabled` | Same as lsp-self-support |
| `perm-declaration` | Yes | `permissions` | write_files, execute_shell, read_env |
| `file-agent` | Yes | `agent_files` | .pi dir (unmanaged) |
| `exec-adapter` | No | — | Not declared |

### OpenCode

| Capability ID | Present | Subject value | Notes |
|---|---|---|---|
| `cli-probe` | Yes | `cli_probe` | probe_fn: _opencode_probe |
| `cli-install` | Yes | `cli_install` | uv install |
| `mcp-config` | Yes | `mcp_config` | .opencode/opencode.json, opencode-json format |
| `lsp-config` | Yes | `language_servers_config` | .opencode/opencode.json, opencode-json format |
| `model-catalog-refresh` | Yes | `fetch_catalog_fn` | opencode models --verbose |
| `surface-render` | Yes | `surfaces` | flat-skill, CLAUDE.md |
| `surface-skill` | Yes | `skill_surface_path` | .claude/skills/{tag}/SKILL.md |
| `surface-instruction` | Yes | `instruction_file` | CLAUDE.md |
| `exec-adapter` | Yes | `execution` | mode: cli |
| `perm-declaration` | Yes | `permissions` | write_files, execute_shell, browse_web, read_env |
| `file-agent` | Yes | `agent_files` | CLAUDE.md (managed), .claude/ (unmanaged) |
| `model-config` | No | — | Blocked: config path unresolved (config.json vs opencode.json) |

### Copilot

| Capability ID | Present | Subject value | Notes |
|---|---|---|---|
| `cli-probe` | Yes | `cli_probe` | probe_fn: _copilot_probe |
| `cli-install` | Yes | `cli_install` | npm: @github/copilot |
| `ext-declaration` | Yes | `host_capabilities` | GitHub.copilot, GitHub.copilot-chat (vscode) |
| `mcp-config` | Yes | `mcp_config` | .mcp.json, mcp-json format |
| `surface-render` | Yes | `surfaces` | flat-skill, COPILOT.md |
| `surface-instruction` | Yes | `instruction_file` | COPILOT.md |
| `exec-adapter` | Yes | `execution` | mode: cli |
| `perm-declaration` | Yes | `permissions` | no write/execute/browse/env |
| `file-agent` | Yes | `agent_files` | COPILOT.md (managed), .github/copilot-instructions.md (unmanaged) |

### Aider

| Capability ID | Present | Subject value | Notes |
|---|---|---|---|
| `cli-probe` | Yes | `cli_probe` | aider --version |
| `cli-install` | Yes | `cli_install` | uv: aider-chat@latest |
| `exec-adapter` | Yes | `execution` | mode: stub |
| `perm-declaration` | Yes | `permissions` | write_files, execute_shell, browse_web, read_env |
| `file-agent` | Yes | `agent_files` | AGENTS.md, .aider.conf.yml (both unmanaged) |

### Gemini

| Capability ID | Present | Subject value | Notes |
|---|---|---|---|
| `cli-probe` | Yes | `cli_probe` | gemini --version |
| `cli-install` | Yes | `cli_install` | npm: @google/gemini-cli |
| `ext-declaration` | Yes | `host_capabilities` | google.gemini-cli-vscode-ide-companion (vscode) |
| `mcp-config` | Yes | `mcp_config` | .gemini/settings.json, mcp-json format |
| `surface-render` | Yes | `surfaces` | flat-skill, GEMINI.md |
| `surface-skill` | Yes | `skill_surface_path` | .gemini/commands/{tag}.md |
| `surface-instruction` | Yes | `instruction_file` | GEMINI.md |
| `depr-status` | Yes | `deprecated` | True, replaced by antigravity |
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
|---|---|---|
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
