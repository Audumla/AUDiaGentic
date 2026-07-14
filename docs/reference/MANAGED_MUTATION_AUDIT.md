# Managed Mutation Audit

Status: MA01 baseline, 2026-07-12.

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
| src/audiagentic/components/memory/hindsight/codex_recipe.py:_download | write_bytes | component-managed | WriteFileStep + ArtifactRegistry | MA02 | Downloaded integration files need owned-file lifecycle. |
| src/audiagentic/components/memory/hindsight/codex_recipe.py:_enable_codex_hooks | write_text | shared-config | ConfigPatcher + ArtifactRegistry | MA02 | Nested `features.codex_hooks`; surgical edit is not exemption. |
| src/audiagentic/components/memory/hindsight/codex_recipe.py:uninstall | rmtree,unlink | component-managed | ArtifactRegistry.prune | MA02 | Remove registered integration artifacts only. |
| src/audiagentic/components/memory/hindsight/pi_recipe.py:configure | write_text | shared-config | ConfigPatcher + ArtifactRegistry | MA02 | Nested Hindsight/Pi keys; brace strings are ordinary values. |
| src/audiagentic/components/memory/hindsight/pi_recipe.py:prune | write_text | shared-config | ArtifactRegistry.prune | MA02 | Prune owned keys, preserve user values. |
| src/audiagentic/components/memory/hindsight/plugin_recipes.py:_repair_windows_plugin_mcp | write_text | third-party-repair | adapter exemption candidate | MA02 | Dynamic plugin-owned file; must gain atomic/preservation tests. |
| src/audiagentic/components/memory/hindsight/plugin_recipes.py:prune | unlink | component-managed | ArtifactRegistry.prune | MA02 | URL config is recipe-owned, not exempt. |
| src/audiagentic/components/providers/adapters/codex/adapter.py:run | unlink | runtime-asset | bounded adapter cleanup | keep | Temporary result file created and removed in same call. |
| src/audiagentic/components/providers/adapters/codex/language_servers.py:_save_toml | write_text | adapter-serializer | atomic foundation writer | MA04 | Valid format extension; atomicity missing. |
| src/audiagentic/components/providers/adapters/codex/mcp_format.py:_save_toml | atomic_write_text | adapter-serializer | atomic foundation writer | keep | Compliant custom TOML serializer. |
| src/audiagentic/components/providers/adapters/continue_/mcp_format.py:remove_continue_json | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Compliant remove serializer. |
| src/audiagentic/components/providers/adapters/continue_/mcp_format.py:write_continue_json | atomic_write_json | adapter-serializer | atomic foundation writer | keep | Compliant upsert serializer. |
| src/audiagentic/components/providers/adapters/goose/mcp_format.py:remove_goose_yaml | atomic_write_text | adapter-serializer | atomic foundation writer | keep | Compliant custom YAML serializer. |
| src/audiagentic/components/providers/adapters/goose/mcp_format.py:write_goose_yaml | atomic_write_text | adapter-serializer | atomic foundation writer | keep | Compliant custom YAML serializer. |
| src/audiagentic/components/providers/adapters/mcp_opencode.py:remove_opencode_mcp | write_text | adapter-serializer | atomic foundation writer | MA04 | Valid format extension; atomicity missing. |
| src/audiagentic/components/providers/adapters/mcp_opencode.py:write_opencode_mcp | write_text | adapter-serializer | atomic foundation writer | MA04 | Valid format extension; atomicity missing. |
| src/audiagentic/components/providers/adapters/opencode/language_servers.py:_save_json | write_text | adapter-serializer | atomic foundation writer | MA04 | Valid format extension; atomicity missing. |
| src/audiagentic/components/providers/adapters/opencode/plugin_array.py:remove_opencode_plugin | write_text | adapter-serializer | atomic foundation writer | MA04 | Named plugin entry needs atomic adapter contract. |
| src/audiagentic/components/providers/adapters/opencode/plugin_array.py:write_opencode_plugin | write_text | adapter-serializer | atomic foundation writer | MA04 | Named plugin entry needs atomic adapter contract. |
| src/audiagentic/components/providers/adapters/openhands/toml_format.py:remove_mcp_toml | write_text | adapter-serializer | atomic foundation writer | MA04 | Valid format extension; atomicity missing. |
| src/audiagentic/components/providers/adapters/openhands/toml_format.py:write_mcp_toml | write_text | adapter-serializer | atomic foundation writer | MA04 | Valid format extension; atomicity missing. |
| src/audiagentic/components/providers/adapters/qwen/language_servers.py:_save_json | write_text | adapter-serializer | atomic foundation writer | MA04 | Valid format extension; atomicity missing. |
| src/audiagentic/components/providers/adapters/qwen/language_servers.py:remove_language_servers_qwen | unlink | adapter-serializer | atomic adapter contract | MA04 | Whole empty-file removal needs contract tests. |
| src/audiagentic/components/providers/skill_surfaces.py:regenerate_skill_surfaces | atomic_write_text | generated-surface | registered renderer | keep | Compliant generated provider surface. |
| src/audiagentic/components/providers/surfaces/extensions_json.py:prune_extensions_json | write_text | generated-surface | registered renderer + atomic writer | MA04 | Correct owner; atomicity missing. |
| src/audiagentic/components/providers/surfaces/extensions_json.py:write_extensions_json | write_text | generated-surface | registered renderer + atomic writer | MA04 | Correct owner; atomicity missing. |
| src/audiagentic/components/providers/surfaces/manager.py:apply_provider_surfaces | atomic_write_text | generated-surface | registered renderer + managed block | keep | Compliant generic surface apply. |
| src/audiagentic/components/providers/surfaces/manager.py:prune_provider_surfaces | atomic_write_text,rmdir,unlink | generated-surface | registered renderer + managed block | keep | Compliant generic surface prune. |
| src/audiagentic/components/release/release_please/finalize.py:render_release_docs | atomic_write_text | component-managed | release manager | keep | Owning component generates release artifacts. |
| src/audiagentic/components/release/release_please/install.py:install | write_text | component-managed | descriptor/WriteFileStep | MA05 | Managed workflow install needs atomic owned-file path. |
| src/audiagentic/components/release/release_please/manage.py:ensure_baseline | atomic_write_text | component-managed | release manager | keep | Compliant baseline management. |
| src/audiagentic/components/release/release_please/manage.py:update_workflow | write_text | component-managed | atomic owned-file path | MA05 | Release-owned workflow write is non-atomic. |
| src/audiagentic/components/source_control/source_control_bootstrap.py:_install_post_commit_hook | write_text | component-managed | managed block + atomic writer | MA05 | Hook is shared user file; block owner exists, atomicity missing. |
| src/audiagentic/components/source_control/source_control_bootstrap.py:_remove_post_commit_hook | unlink,write_text | component-managed | managed block + atomic writer | MA05 | Remove owned block/file only and write atomically. |
| src/audiagentic/runtime/harness/opencode/install/__init__.py:materialize_agent_config | write_text | shared-config | managed config + surface manager | MA03 | Runtime duplicates MCP/model/surface ownership. |
| src/audiagentic/runtime/harness/pi/install/__init__.py:_seed_test_model | copyfile | runtime-asset | harness asset installer | keep | Harness-owned test/model asset. |
| src/audiagentic/runtime/harness/pi/install/__init__.py:uninstall_from | rmtree | runtime-asset | harness asset installer | keep | Removes harness-owned runtime directories. |
| src/audiagentic/runtime/harness/pi/install/config.py:_build_settings_config | write_text | runtime-asset | harness asset materializer | keep | Writes harness-owned settings staging file. |
| src/audiagentic/runtime/harness/pi/install/config.py:_build_system_md | write_text | runtime-asset | harness asset materializer | MA03 | Verify provider surface ownership; consolidate if project-facing. |
| src/audiagentic/runtime/harness/pi/install/config.py:materialize_agent_config | copytree,unlink,write_text | shared-config | managed config + surface manager | MA03 | Split runtime assets from provider/project config. |
| src/audiagentic/runtime/harness/pi/install/patches.py:_patch_interactive_mode | write_text | third-party-repair | adapter exemption candidate | MA03 | Patches installed third-party package; test exemption gates. |
| src/audiagentic/runtime/harness/pi/install/patches.py:_patch_mcp_explicit_config_only | write_text | third-party-repair | adapter exemption candidate | MA03 | Patches installed third-party package. |
| src/audiagentic/runtime/harness/pi/install/patches.py:_patch_mcp_oauth_suppress | write_text | third-party-repair | adapter exemption candidate | MA03 | Patches installed third-party package. |
| src/audiagentic/runtime/harness/pi/install/patches.py:_patch_slash_commands | write_text | third-party-repair | adapter exemption candidate | MA03 | Patches installed third-party package. |
| src/audiagentic/runtime/harness/pi/install/patches.py:_patch_tool_execution | write_text | third-party-repair | adapter exemption candidate | MA03 | Patches installed third-party package. |
| src/audiagentic/runtime/harness/pi/install/patches.py:_patch_update_notification | write_text | third-party-repair | adapter exemption candidate | MA03 | Patches installed third-party package. |
| src/audiagentic/runtime/harness/pi/install/patches_mcp_progress.py:_patch_mcp_direct_tools_progress | write_text | third-party-repair | adapter exemption candidate | MA03 | Patches installed third-party package. |
| src/audiagentic/runtime/harness/pi/install/patches_mcp_progress.py:_patch_mcp_proxy_progress | write_text | third-party-repair | adapter exemption candidate | MA03 | Patches installed third-party package. |
| src/audiagentic/runtime/harness/pi/install/patches_mcp_register.py:_patch_mcp_direct_tools_live_register | write_text | third-party-repair | adapter exemption candidate | MA03 | Patches installed third-party package. |
| src/audiagentic/runtime/harness/pi/mcp_format.py:remove_pi_mcp_json | atomic_write_json | adapter-serializer | registered provider serializer | MA03 | Duplicate runtime serializer/lifecycle wrapper. |
| src/audiagentic/runtime/harness/pi/mcp_format.py:write_pi_mcp_json | atomic_write_json | adapter-serializer | registered provider serializer | MA03 | Duplicate runtime serializer/lifecycle wrapper. |

## Non-mutation architecture findings

| finding | owner | remedy |
|---|---|---|
| `memory/hindsight/strategies.py::_build_hooks_recipe` branches on `codex`, `pi`, `aider` | MA02 | Descriptor/matrix implementation refs and registry dispatch. |
| Architecture test checks only `build_hindsight_recipe`, missing helper branches | MA01/MA02 | Scan all generic strategy comparisons. |
| Artifact registry loading treats corrupt registries as empty | MA02 | Canonical corruption error; never erase ownership silently. |

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
