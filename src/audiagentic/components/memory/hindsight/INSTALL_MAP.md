# Provider to Hindsight Installation Map

This is the canonical human-readable map of every AUDiaGentic provider descriptor
to the Hindsight integration route selected by the Hindsight provisioning contract.

It is documentation, not an executable dispatch matrix. Runtime selection remains
capability-driven through `list_provider_descriptors()` and the fixed preference
order in `provision.py`:

1. `managed-hooks`
2. `managed-mcp`
3. `plugin-entry`
4. guidance-only when none of those families is advertised

The **Hindsight materialization lifecycle** column is normative design intent. It
states exactly what install, ongoing management, and uninstall must do for each
provider. Implementation work may land separately, but must conform to this
contract.

## Summary

- Current provider descriptors: **16**
- Resolved to managed hooks: **1**
- Resolved to managed MCP: **12**
- Resolved to plugin entry: **0**
- Guidance-only: **3**
- Deprecated provider retained in the registry: **Gemini**, replaced by Antigravity

## Lifecycle semantics

For this document:

- **Install** means materializing the Hindsight capability when the provider and
  Hindsight are enabled.
- **Manage** means idempotent reconcile and status behavior after installation:
  update changed backend values, repair missing or stale owned artifacts, preserve
  unowned provider configuration, report collisions, and apply the provider's
  refresh policy.
- **Uninstall** means removing only Hindsight-owned entries and artifacts when
  Hindsight is disabled or the provider becomes stale/disabled. Unrelated provider
  configuration must remain untouched.

Managed MCP entries use stable managed ID `ag-hindsight`. Ownership is recorded in
the managed-MCP ownership registry under the provider plus Hindsight caller scope.
Repeated installation updates the owned entry rather than duplicating it.

### Lifecycle behavior implementation status (DE03)

| Behavior | Implemented | How | Notes |
| --- | --- | --- | --- |
| Report restart-required after changes | ✅ Yes | `_lifecycle_hint` reads `changed` + `auto_refreshed` from managed result; fallback to descriptor `refresh_mode` via `_mcp_refresh_mode` | Applied in reconcile (all providers) and status report (managed-mcp only). File-watch providers (antigravity, claude, qwen, opencode) get NO restart hint. |
| Rely on file-watch reload | ✅ Yes | File-watch providers have `auto_refreshed=True` in managed result; `_lifecycle_hint` skips restart hint when `changed=True` but auto-refreshed | No explicit "file-watch" message — absence of restart hint signals reload is automatic. |
| Report collisions | ✅ Yes | `_lifecycle_hint` checks `collision_ids` in managed result; `_map_mcp_status` surfaces them in status report | Collisions surfaced even on ok (not dropped as before DE03). |
| Surface deprecation/migration guidance | ✅ Yes (boolean only) | `_lifecycle_hint` reads `desc.deprecated` via `get_descriptor`; applied in both reconcile and status | No structured block — only boolean flag exists. No replacement_provider/message surfaced; user must check annotations. |

> **Not yet implemented:** Docker env-changing validation (DE03 step 6),
> per-provider structured deprecation with replacement provider messaging.

## Runtime installation references

### H1 — managed hooks

Used by Codex because `managed-hooks` has precedence over its `managed-mcp`
capability. Provider-owned hook entries are reconciled through:

```text
components/memory/hindsight/provision.py::_apply_hooks
  -> _build_codex_hook_entries
  -> providers/providers_api.py::manage_hook_entries
  -> Codex hooks reader/writer/remover
```

The intended Codex recipe separately owns `~/.hindsight/codex.json` and the hook
scripts under `~/.hindsight/codex/scripts/`.

### M1 — managed MCP

The standard route for providers that advertise `managed-mcp` and do not resolve
to managed hooks first:

```text
components/memory/hindsight/provision.py::_apply_mcp
  -> components/memory/hindsight/mcp_recipe.py::build_hindsight_managed_entry
  -> providers/providers_api.py::manage_mcp_entries
  -> provider descriptor mcp_config reader/writer/remover
```

HTTP/SSE entries point to the backend's `/mcp` endpoint and include
`Authorization` and `X-Bank-Id` headers when configured. Stdio entries use
`hindsight-mcp --base-url <base-url>`. A provider marked stdio-only must receive
the stdio form.

### R1 — Hindsight-owned artifact recipes

Files under `~/.hindsight/*` are Hindsight-owned rather than provider-owned. The
intended contract provisions them declaratively and reconciles them independently
from the selected provider family:

```text
provision.py::_ARTIFACT_RECIPES
  -> foundation/toolchains/recipe_execution.py::execute_recipe_mode
  -> config/components/memory/recipes/<recipe>.yaml
```

- `hindsight-codex.yaml` owns the Codex hook scripts and
  `~/.hindsight/codex.json`.
- `hindsight-pi.yaml` owns the Pi host block in
  `~/.hindsight/config.json`.

Only Codex and Pi require R1 artifacts.

### P1 — plugin entry

Implemented through `providers_api.manage_plugin_entry`, but currently selected by
no provider. OpenCode advertises both `managed-mcp` and `plugin-entry`; managed MCP
wins by preference order.

### G1 — guidance-only

No provider artifact is written. Status remains not registered, and uninstall is a
no-op because AUDiaGentic owns nothing for that provider.

## Current provider map

| Provider | Descriptor | State | Advertised relevant families | Selected route | Provider destination/install reference | Hindsight materialization lifecycle — install / manage / uninstall | Upstream Hindsight reference |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Aider (`aider`) | `config/providers/aider.yaml` | Active | none | **G1** | No managed destination | **Install:** do not mutate Aider; return guidance-only and point to manual/direct integration guidance. **Manage:** no owned state; report not registered. **Uninstall:** no-op because AUDiaGentic created nothing. | [Aider integration](https://hindsight.vectorize.io/sdks/integrations/aider) existed in the retired matrix, but its wrapper installer is not invoked by this route. |
| Antigravity (`antigravity`) | `config/providers/antigravity.yaml` | Active; Gemini replacement | `managed-mcp` | **M1** | `~/.gemini/antigravity/mcp_config.json`; MCP JSON; file-watch | **Install:** write or replace owned `ag-hindsight` MCP entry through the descriptor JSON writer. **Manage:** read and compare the entry on reconcile, update URL/headers/command when backend settings change, preserve other servers, and rely on file-watch reload. **Uninstall:** remove only the registry-owned `ag-hindsight` entry with the descriptor remover and clear its ownership record. | No Antigravity-specific direct installer is recorded; support is generic managed MCP. |
| Claude (`claude`) | `config/providers/claude.yaml` | Active | `managed-mcp` | **M1** | `~/.claude/mcp.json`; MCP JSON; file-watch | **Install:** write or replace owned `ag-hindsight` in Claude's MCP JSON. **Manage:** reconcile the full desired entry, repair missing/stale values, preserve user MCP servers, and rely on Claude's file watcher. **Uninstall:** remove only the Hindsight-owned entry and registry mapping; do not remove Claude or its other MCP configuration. | [Claude Code integration](https://hindsight.vectorize.io/sdks/integrations/claude-code); the upstream plugin is not this route. |
| Cline (`cline`) | `config/providers/cline.yaml` | Active | `managed-mcp` | **M1** | `.cline/mcp.json`; MCP JSON; restart-required | **Install:** write or replace owned `ag-hindsight` in project Cline MCP config. **Manage:** reconcile owned state and preserve unowned entries; report that Cline/its host must restart after a change. **Uninstall:** remove only `ag-hindsight`, clear ownership, and report restart-required when removal changed the file. | [Cline integration](https://hindsight.vectorize.io/sdks/integrations/cline); the upstream hook installer is not this route. |
| Codex (`codex`) | `config/providers/codex.yaml` | Active | `managed-hooks`, `managed-mcp` | **H1** + **R1** | `~/.codex/hooks.json` via Codex hooks writer; `~/.hindsight/codex.json`; `~/.hindsight/codex/scripts/`; restart-required | **Install:** R1 downloads/updates Hindsight Codex scripts, writes the Hindsight backend/bank/token config, then H1 installs owned `SessionStart`, `UserPromptSubmit`, and `Stop` hook commands pointing to `session_start.py`, `recall.py`, and `retain.py`. **Manage:** reconcile script versions, backend config, and the three stable hook entries; preserve non-Hindsight hooks and pre-existing unowned settings; report restart-required after hook changes. **Uninstall:** remove only Hindsight-owned hook entries, remove recipe-owned Codex config keys/files and downloaded scripts, and preserve unrelated Codex hooks/settings. | [Codex integration](https://hindsight.vectorize.io/sdks/integrations/codex); scripts originate from `vectorize-io/hindsight/main/hindsight-integrations/codex`. |
| Continue (`continue`) | `config/providers/continue.yaml` | Active | `managed-mcp` | **M1** | `.continue/config.json`; Continue JSON; restart-required | **Install:** write or replace owned `ag-hindsight` through the Continue-specific JSON adapter. **Manage:** reconcile the owned entry without disturbing the rest of Continue config; report restart-required after any change. **Uninstall:** remove only the Hindsight entry and ownership mapping, then report restart-required if the file changed. | [Continue integration](https://hindsight.vectorize.io/sdks/integrations/continue); the upstream context-provider installer is not this route. |
| GitHub Copilot (`copilot`) | `config/providers/copilot.yaml` | Active | `managed-mcp` | **M1** | `.mcp.json`; MCP JSON; restart-required | **Install:** add or replace owned `ag-hindsight` in project `.mcp.json`. **Manage:** reconcile exact entry content, preserve all non-Hindsight MCP servers, and report that Copilot/VS Code must restart or reload after changes. **Uninstall:** remove only the owned Hindsight server and clear registry ownership. | [GitHub Copilot integration](https://hindsight.vectorize.io/sdks/integrations/github-copilot); this route uses generic managed MCP. |
| Gemini (`gemini`) | `config/providers/gemini.yaml` | **Deprecated**; replacement `antigravity` | `managed-mcp` | **M1** | `.gemini/settings.json`; MCP JSON; restart-required | **Install:** while the deprecated provider remains enabled, write or replace owned `ag-hindsight` in Gemini project settings. **Manage:** reconcile only the owned MCP entry and surface both restart-required and deprecation/migration guidance. **Uninstall:** remove only the Hindsight entry and ownership mapping; leave all other Gemini settings intact. | [Gemini Spark integration](https://hindsight.vectorize.io/sdks/integrations/gemini-spark); retained only while the deprecated provider exists. |
| Goose (`goose`) | `config/providers/goose.yaml` | Active | `managed-mcp` | **M1** | `.goose/config.yaml`; Goose YAML; stdio-only; restart-required | **Install:** materialize `ag-hindsight` as a stdio `hindsight-mcp --base-url ...` extension through the Goose YAML writer; remote URL form is forbidden. **Manage:** reconcile command/args/env, preserve other Goose extensions, and report restart-required after changes. **Uninstall:** remove only the owned Goose Hindsight extension and registry entry, then report restart-required. | No direct upstream integration recorded; support is the Goose-specific managed-MCP YAML adapter. |
| Local OpenAI Bridge (`local-openai`) | `config/providers/local_openai.yaml` | Active | none | **G1** | No managed destination | **Install:** no provider mutation because this is an endpoint bridge, not a harness with a managed Hindsight surface. **Manage:** report not registered and provide guidance only. **Uninstall:** no-op. | No direct upstream integration recorded. |
| OpenCode (`opencode`) | `config/providers/opencode.yaml` | Active | `managed-mcp`, `plugin-entry` | **M1** | `.opencode/opencode.json`; OpenCode MCP object; file-watch | **Install:** write or replace owned `ag-hindsight` in the MCP section of `opencode.json`; do not install the Hindsight plugin because M1 wins. **Manage:** reconcile the MCP object, preserve plugins, language servers, models, and unowned MCP entries, and rely on file-watch reload. **Uninstall:** remove only the managed MCP object and ownership mapping; leave the plugin array untouched. | [OpenCode integration](https://hindsight.vectorize.io/sdks/integrations/opencode); the upstream plugin is deliberately not selected. |
| OpenHands (`openhands`) | `config/providers/openhands.yaml` | Active | `managed-mcp` | **M1** | `.openhands/config.toml`; MCP TOML; restart-required | **Install:** write or replace owned `ag-hindsight` in the MCP portion of OpenHands TOML. **Manage:** reconcile the exact owned entry, preserve unrelated TOML sections and MCP servers, and report restart-required. **Uninstall:** remove only the Hindsight MCP block and ownership mapping; preserve all other OpenHands configuration. | [OpenHands integration](https://hindsight.vectorize.io/sdks/integrations/openhands); this route is descriptor-backed generic MCP. |
| Pi Coding Agent (`pi`) | `config/providers/pi.yaml` | Active | `managed-mcp` | **M1** + **R1** | `.mcp.json`; MCP JSON; `~/.hindsight/config.json` Pi host block; restart-required | **Install:** M1 writes owned `ag-hindsight` to project `.mcp.json` for pi-mcp-adapter discovery; R1 writes the Pi-specific Hindsight host block (`enabled`, recall settings, backend/bank/auth values) in `~/.hindsight/config.json`. **Manage:** reconcile both artifacts independently, update backend and recall settings, preserve other MCP servers and other Hindsight hosts, and report Pi restart-required after MCP changes. **Uninstall:** remove only `ag-hindsight` plus its ownership mapping and remove only the recipe-owned Pi host block/keys; preserve all unrelated Pi and Hindsight configuration. | No direct upstream integration recorded; support is managed MCP plus a Hindsight-owned Pi host configuration. |
| Plandex (`plandex`) | `config/providers/plandex.yaml` | Active | none | **G1** | No managed destination | **Install:** do not mutate Plandex; return guidance-only. **Manage:** no owned state and status remains not registered. **Uninstall:** no-op. | No direct upstream integration recorded. |
| Qwen (`qwen`) | `config/providers/qwen.yaml` | Active | `managed-mcp` | **M1** | `.mcp.json`; MCP JSON; file-watch | **Install:** add or replace owned `ag-hindsight` in project `.mcp.json`. **Manage:** reconcile desired transport/endpoint/auth values, preserve non-Hindsight servers, and rely on Qwen's file watcher. **Uninstall:** remove only the owned Hindsight entry and clear its ownership record. | No direct upstream integration recorded; support is generic managed MCP. |
| Roo Code (`roo`) | `config/providers/roo.yaml` | Active | `managed-mcp` | **M1** | `.mcp.json`; MCP JSON; restart-required | **Install:** add or replace owned `ag-hindsight` in project `.mcp.json` used by Roo Code. **Manage:** reconcile exact entry content, preserve unrelated servers, and report VS Code/Roo restart-required after changes. **Uninstall:** remove only the Hindsight entry and ownership mapping; do not alter the Roo extension or other project configuration. | [Roo Code integration](https://hindsight.vectorize.io/sdks/integrations/roo-code); this route uses generic managed MCP. |

## Removed stale matrix rows

The retired Hindsight matrix contained `cursor` and `windsurf`. Neither has a
current provider descriptor, so neither belongs in the active AUDiaGentic map.

The retired matrix did not contain `antigravity`; it was added after that matrix
was written and replaces the deprecated Gemini provider.

## Important behavior notes

1. **The lifecycle column is the contract.** A provider implementation is incomplete
   until install, idempotent management/status, stale-provider pruning, and full
   owned-artifact uninstall match its row.
2. **An upstream Hindsight integration does not mean AUDiaGentic invokes it.** The
   selected route is determined by current provider capabilities and family
   preference.
3. **OpenCode resolves to managed MCP, not its upstream plugin.** Changing that
   requires changing family precedence or provider capabilities.
4. **Guidance-only is not installation.** Aider, Local OpenAI Bridge, and Plandex
   receive no Hindsight-owned provider artifact.
5. **Codex and Pi are compound materializations.** Their provider-owned family
   artifacts and Hindsight-owned R1 artifacts must both succeed, reconcile, report
   status, and uninstall cleanly.
6. **Uninstall is ownership-scoped.** It must never delete manually configured MCP
   servers, hooks, plugins, provider settings, or Hindsight host blocks belonging
   to another integration.
7. **Gemini remains mapped only while its deprecated descriptor exists.** New work
   should target Antigravity.

## Drift checklist

Update this file whenever any of the following changes:

- a provider is added or removed;
- a provider adds or removes `managed-hooks`, `managed-mcp`, or `plugin-entry`;
- `_hindsight_families()` changes order;
- a provider config path, format, transport capability, or refresh mode changes;
- the managed entry ID or ownership-scope rules change;
- an R1 artifact recipe is added, removed, or retargeted;
- install, status/reconcile, stale-prune, or uninstall behavior changes;
- an upstream direct Hindsight integration is added, removed, or superseded.

The executable implementation must remain aligned with this document without
turning the document itself into runtime dispatch data.
