# Managed Mutation Audit

Status: MA06/MA27 revalidated, 2026-07-18.

Scope is shared external configuration, generated surfaces, adapter serializers, and
runtime materializers under `src/audiagentic`. Owning-component domain records
(planning items, jobs, ledgers, catalogs, event stores), generic foundation primitives,
runtime logs/state/cache, credential stores, and package/binary installation are
explicitly excluded; they retain their owning store/lifecycle.

Machine contract: each inventory row has one exact `path:symbol`. Architecture tests
scan declared scope and require exact set equality with this table.

Categories: `shared-config`, `adapter-serializer`, `generated-surface`,
`component-managed`, `runtime-asset`, `third-party-repair`.

| path:symbol | mutations | category | primitive | action | rationale |
|---|---|---|---|---|---|
| src/audiagentic/components/memory/hindsight/provision.py:_download_codex_scripts | atomic_write_text | component-managed | atomic foundation writer | keep | Hindsight-owned UTF-8 hook assets preserve their upstream relative paths and settings remains user-preserving when already present. |
| src/audiagentic/components/providers/adapters/codex/adapter.py:run | unlink | runtime-asset | bounded adapter cleanup | keep | Temporary result file created and removed in same call. |
| src/audiagentic/components/providers/adapters/codex/hooks_format.py:_enable_codex_hooks | atomic_write_text | adapter-serializer | surgical shared-config upsert | keep | Current Codex `features.hooks` is a single-key shared-config mutation; the adapter migrates the deprecated `features.codex_hooks` key and prune never disables hooks. |
| src/audiagentic/components/providers/adapters/codex/hooks_format.py:_save_hooks | atomic_write_text | adapter-serializer | atomic foundation writer | keep | Codex hooks JSON serializer preserves foreign hooks through managed-config reconciliation. |
| src/audiagentic/components/providers/adapters/codex/hooks_format.py:remove_codex_hook | unlink | adapter-serializer | atomic adapter contract | keep | Removes owned hook entries only; unlinks only after the hooks section becomes empty. |
| src/audiagentic/components/providers/adapters/codex/language_servers.py:_save_toml | atomic_write_text | adapter-serializer | atomic foundation writer | keep | Compliant custom TOML serializer with atomic write (verified MA04, 2026-07-14). |
| src/audiagentic/components/providers/adapters/codex/mcp_format.py:_save_toml | atomic_write_text | adapter-serializer | atomic foundation writer | keep | Compliant custom TOML serializer. |
| src/audiagentic/components/providers/adapters/continue_/mcp_format.py:remove_continue_json | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Compliant remove serializer. |
| src/audiagentic/components/providers/adapters/continue_/mcp_format.py:write_continue_json | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Compliant upsert serializer. |
| src/audiagentic/components/providers/adapters/goose/mcp_format.py:remove_goose_yaml | atomic_write_text | adapter-serializer | atomic foundation writer | keep | Compliant custom YAML serializer. |
| src/audiagentic/components/providers/adapters/goose/mcp_format.py:write_goose_yaml | atomic_write_text | adapter-serializer | atomic foundation writer | keep | Compliant custom YAML serializer. |
| src/audiagentic/components/providers/adapters/opencode/mcp_format.py:remove_opencode_mcp | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Migrated to atomic_write_json (MA04, 2026-07-14) and colocated with the OpenCode adapter. |
| src/audiagentic/components/providers/adapters/opencode/mcp_format.py:write_opencode_mcp | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Migrated to atomic_write_json (MA04, 2026-07-14) and colocated with the OpenCode adapter. |
| src/audiagentic/components/providers/adapters/opencode/model_config.py:_write_registry | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Writes the provider-owned OpenCode model registry atomically. |
| src/audiagentic/components/providers/adapters/opencode/model_config.py:remove_opencode_model | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Reconciles model removal while preserving the provider-owned registry shape. |
| src/audiagentic/components/providers/adapters/opencode/model_config.py:write_opencode_models | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Reconciles OpenCode model entries through the provider serializer. |
| src/audiagentic/components/providers/adapters/opencode/language_servers.py:write_language_servers_opencode | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Migrated to foundation primitives, consolidated load helper (MA04, 2026-07-14). |
| src/audiagentic/components/providers/adapters/opencode/language_servers.py:remove_language_servers_opencode | atomic_write_json | adapter-serializer | atomic adapter contract | keep | Atomic write with empty-container cleanup (verified MA04, 2026-07-14). |
| src/audiagentic/components/providers/adapters/opencode/plugin_array.py:remove_opencode_plugin | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Migrated to atomic_write_json, consolidated load helper (MA04 follow-on, 2026-07-14). |
| src/audiagentic/components/providers/adapters/opencode/plugin_array.py:write_opencode_plugins | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Migrated to atomic_write_json, consolidated load helper (MA04 follow-on, 2026-07-14). Reshaped to name-keyed dict interface (MA20, 2026-07-15). |
| src/audiagentic/components/providers/adapters/openhands/toml_format.py:remove_mcp_toml | atomic_write_text | adapter-serializer | atomic foundation writer | keep | Migrated to atomic_write_text (MA04, 2026-07-14). |
| src/audiagentic/components/providers/adapters/openhands/toml_format.py:write_mcp_toml | atomic_write_text | adapter-serializer | atomic foundation writer | keep | Migrated to atomic_write_text (MA04, 2026-07-14). |
| src/audiagentic/components/providers/adapters/qwen/language_servers.py:write_language_servers_qwen | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Migrated to foundation primitives, consolidated load helper (MA04, 2026-07-14). |
| src/audiagentic/components/providers/adapters/qwen/language_servers.py:remove_language_servers_qwen | unlink,atomic_write_json | adapter-serializer | atomic adapter contract | keep | Contract-tested whole-file removal and atomic write (MA04, 2026-07-14). |
| src/audiagentic/components/providers/adapters/pi/acp.py:_materialize_pi_command_wrapper | atomic_write_text | runtime-asset | provider launch-surface materializer | keep | Creates a job-scoped ACP wrapper inside the caller-owned ephemeral runtime root. |
| src/audiagentic/components/providers/adapters/pi/mcp_exclusive_patch.py:apply_mcp_exclusive_patch | write_text | third-party-repair | provider lifecycle patch | keep | Applies the version-gated Pi exclusive-MCP launch patch during explicit provisioning. |
| src/audiagentic/components/providers/adapters/pi/mcp_surface.py:_materialize_launch_config | atomic_write_json | runtime-asset | provider launch-surface materializer | keep | Writes a job-scoped MCP file atomically inside the caller-owned ephemeral runtime root. |
| src/audiagentic/components/providers/skill_surfaces.py:regenerate_skill_surfaces | atomic_write_text | generated-surface | registered renderer | keep | Compliant generated provider surface. |
| src/audiagentic/components/providers/surfaces/extensions_json.py:prune_extensions_json | atomic_write_json | generated-surface | registered renderer + atomic writer | keep | Migrated to atomic_write_json, consolidated load helper (MA04 follow-on, 2026-07-14). |
| src/audiagentic/components/providers/surfaces/extensions_json.py:write_extensions_json | atomic_write_json | generated-surface | registered renderer + atomic writer | keep | Migrated to atomic_write_json, consolidated load helper (MA04 follow-on, 2026-07-14). |
| src/audiagentic/components/providers/surfaces/manager.py:apply_provider_surfaces | atomic_write_text | generated-surface | registered renderer + managed block | keep | Compliant generic surface apply. |
| src/audiagentic/components/providers/surfaces/manager.py:prune_provider_surfaces | atomic_write_text,rmdir,unlink | generated-surface | registered renderer + managed block | keep | Compliant generic surface prune. |
| src/audiagentic/components/release/release_please/finalize.py:render_release_docs | atomic_write_text | component-managed | release manager | keep | Owning component generates release artifacts. |
| src/audiagentic/components/release/release_please/install.py:install | atomic_write_text | component-managed | descriptor/WriteFileStep + ArtifactRegistry | keep | Atomic whole-file install with adoption/collision logic and ownership registration. |
| src/audiagentic/components/release/release_please/manage.py:ensure_baseline | atomic_write_text | component-managed | release manager | keep | Compliant baseline management. |
| src/audiagentic/components/release/release_please/manage.py:update_workflow | atomic_write_text | component-managed | atomic owned-file path | keep | Release-owned workflow update uses atomic write. |
| src/audiagentic/components/source_control/source_control_bootstrap.py:_install_hook_absent | atomic_write_text | component-managed | atomic writer + ArtifactRegistry | keep | Creates fresh whole-owned hook file atomically. |
| src/audiagentic/components/source_control/source_control_bootstrap.py:prune_post_commit_hook | unlink | component-managed | ArtifactRegistry prune proof | keep | Whole-owned deletion only with registry proof; block-owned preserves user file. |
| src/audiagentic/components/source_control/source_control_bootstrap.py:_legacy_remove_fallback | atomic_write_text,unlink | component-managed | managed block + atomic writer | keep | Legacy hook removal for pre-managed-block marker format. |
| src/audiagentic/components/source_control/source_control_bootstrap.py:_safe_unlink_on_prune | unlink | component-managed | ArtifactRegistry prune proof | keep | Deletes whole-owned file only after registry verification. |
| src/audiagentic/runtime/harness/opencode/install/__init__.py:materialize_agent_config | write_text | shared-config | managed config + surface manager | MA03 | Runtime duplicates MCP/model/surface ownership. |
| src/audiagentic/runtime/harness/pi/install/__init__.py:_seed_test_model | copyfile | runtime-asset | harness asset installer | keep | Harness-owned test/model asset. |
| src/audiagentic/runtime/harness/pi/install/__init__.py:cleanup_runtime | rmtree | runtime-asset | harness asset installer | keep | Removes harness-owned runtime directories during explicit lifecycle cleanup. |
| src/audiagentic/runtime/harness/pi/install/config.py:_build_settings_config | write_text | runtime-asset | harness asset materializer | keep | Writes harness-owned settings staging file. |
| src/audiagentic/runtime/harness/pi/install/config.py:_build_system_md | write_text | runtime-asset | harness asset materializer | MA03 | Verify provider surface ownership; consolidate if project-facing. |
| src/audiagentic/runtime/harness/pi/install/config.py:materialize_agent_config | copytree,unlink,write_text | shared-config | managed config + surface manager | MA03 | Split runtime assets from provider/project config. |
| src/audiagentic/runtime/harness/pi/mcp_format.py:remove_pi_mcp_json | atomic_write_json | adapter-serializer | registered provider serializer | MA03 | Duplicate runtime serializer/lifecycle wrapper. |
| src/audiagentic/runtime/harness/pi/mcp_format.py:write_pi_mcp_json | atomic_write_json | adapter-serializer | registered provider serializer | MA03 | Duplicate runtime serializer/lifecycle wrapper. |
| src/audiagentic/components/providers/adapters/pi/model_config.py:write_pi_models | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Compliant Pi model config serializer using atomic_write_json. |
| src/audiagentic/components/providers/adapters/pi/model_config.py:remove_pi_model | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Compliant Pi model removal via conditional atomic_write_json. |

## Non-mutation architecture findings

| finding | owner | remedy |
|---|---|---|
No open non-mutation findings remain from the MA02/MA27 Hindsight migration. The
former matrix/strategy implementation is deleted, and managed-fragment registry
corruption raises the canonical ownership error rather than erasing state.

Closed (MO06): `lsp_projection.py` no longer calls `spec.writer`/`spec.remover`
directly — routed through `apply_managed_config_write`/`apply_managed_config_remove`
in `foundation/toolchains/managed_config.py`. `providers/descriptors/base.py` no
longer imports `coding_lsp.LanguageServerEntry` — `ManagedConfigSpec`'s
reader/writer/remover are `Any`-typed (domain-opaque). Managed-fragment
registry loading (`ManagedFragmentRegistry`) now raises `CON-MCFG-001` on a
corrupt file instead of silently treating it as empty.

## Explicit exclusions

- Component stores: planning, agent-jobs, agents, ledger, interaction, event store,
  provider catalogs/config state, feature state.
- Foundation mutation primitives: `foundation/io.py`, toolchain patcher, artifact
  registry, managed blocks, lifecycle baseline sync.
- Runtime logs, PID/client markers, caches, rig state/binaries, update staging.
- Credential store and explicit auth-token lifecycle.
- Package installation/uninstallation and temporary execution files.

Exclusions are shape/ownership based, not permission to bypass atomic IO, redaction,
or owning-component contracts.
