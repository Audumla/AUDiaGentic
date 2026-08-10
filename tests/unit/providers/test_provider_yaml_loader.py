"""Tests for components/providers/descriptors/loader.py — provider YAML loader.

Validates that the provider loader can build ProviderDescriptor instances
from YAML files and that the loaded descriptors match the current Python
objects field-by-field.
"""
from __future__ import annotations

import pytest

from audiagentic.components.providers.descriptors.base import (
    ProviderDescriptor,
)
from audiagentic.components.providers.descriptors.loader import (
    PROVIDER_SPEC,
    get_providers_config_dir,
    load_provider_descriptor,
    load_providers_from_directory,
)
from audiagentic.foundation.mcp.json_format import (
    read_mcp_json,
    remove_mcp_json,
    write_mcp_json,
)


class TestProviderYamlLoader:
    """Test provider YAML loading and field fidelity."""

    def test_load_claude_yaml(self) -> None:
        """Load claude.yaml and verify all fields."""
        config_dir = get_providers_config_dir()
        claude_path = config_dir / "claude.yaml"
        if not claude_path.exists():
            pytest.skip("claude.yaml not yet created")

        descriptor = load_provider_descriptor(claude_path)
        assert isinstance(descriptor, ProviderDescriptor)
        assert descriptor.provider_id == "claude"
        assert descriptor.display_name == "Claude (Anthropic)"
        assert descriptor.prompt_aliases == ("cld",)
        assert descriptor.cli_probe == ["claude", "--version"]
        assert descriptor.cli_install is not None
        assert descriptor.cli_install.executable == "claude"
        assert descriptor.mcp_config is not None
        # Project-local .mcp.json via a resolver callable, not a literal
        # home-scoped path (CC55: Claude moved off ~/.claude/mcp.json).
        assert callable(descriptor.mcp_config.config_path)
        assert descriptor.mcp_config.config_path.__name__ == "resolve_claude_mcp_config_path"
        assert descriptor.mcp_config.reader is read_mcp_json
        assert descriptor.mcp_config.writer is write_mcp_json
        assert descriptor.mcp_config.remover is remove_mcp_json
        capability = descriptor.automation_capability("managed-mcp")
        assert capability is not None
        assert capability.supported_modes == ("apply", "prune", "status")
        assert capability.ownership_scope_required is True

    def test_claude_permissions(self) -> None:
        """Claude permissions match expected values."""
        config_dir = get_providers_config_dir()
        claude_path = config_dir / "claude.yaml"
        if not claude_path.exists():
            pytest.skip("claude.yaml not yet created")

        descriptor = load_provider_descriptor(claude_path)
        assert descriptor.permissions.can_write_files is True
        assert descriptor.permissions.can_execute_shell is True
        assert descriptor.permissions.can_browse_web is True
        assert descriptor.permissions.can_read_env is True

    def test_claude_agent_files(self) -> None:
        """Claude agent files are loaded correctly."""
        config_dir = get_providers_config_dir()
        claude_path = config_dir / "claude.yaml"
        if not claude_path.exists():
            pytest.skip("claude.yaml not yet created")

        descriptor = load_provider_descriptor(claude_path)
        assert len(descriptor.agent_files) == 3
        assert descriptor.agent_files[0].rel_path == "CLAUDE.md"
        assert descriptor.agent_files[0].managed is True

    def test_claude_host_capabilities(self) -> None:
        """Claude VS Code extension is loaded correctly."""
        config_dir = get_providers_config_dir()
        claude_path = config_dir / "claude.yaml"
        if not claude_path.exists():
            pytest.skip("claude.yaml not yet created")

        descriptor = load_provider_descriptor(claude_path)
        assert len(descriptor.host_capabilities) == 1
        assert descriptor.host_capabilities[0].host == "vscode"
        assert descriptor.host_capabilities[0].capability_id == "anthropic.claude-code"

    def test_claude_fetch_catalog_fn(self) -> None:
        """Claude fetch_catalog_fn resolves to callable."""
        config_dir = get_providers_config_dir()
        claude_path = config_dir / "claude.yaml"
        if not claude_path.exists():
            pytest.skip("claude.yaml not yet created")

        descriptor = load_provider_descriptor(claude_path)
        assert descriptor.fetch_catalog_fn is not None
        assert callable(descriptor.fetch_catalog_fn)

    def test_load_pi_yaml(self) -> None:
        """Load pi.yaml and verify callable install/uninstall."""
        config_dir = get_providers_config_dir()
        pi_path = config_dir / "pi.yaml"
        if not pi_path.exists():
            pytest.skip("pi.yaml not yet created")

        descriptor = load_provider_descriptor(pi_path)
        assert descriptor.provider_id == "pi"
        assert descriptor.access_mode == "none"
        assert descriptor.cli_install is not None
        assert descriptor.cli_install.package_manager == "pi-harness"
        assert descriptor.on_lsp_enabled is not None
        assert callable(descriptor.on_lsp_enabled)

    def test_pi_callable_steps(self) -> None:
        """Pi install/uninstall steps are callable."""
        config_dir = get_providers_config_dir()
        pi_path = config_dir / "pi.yaml"
        if not pi_path.exists():
            pytest.skip("pi.yaml not yet created")

        descriptor = load_provider_descriptor(pi_path)
        from audiagentic.foundation.steps import CallableStep

        assert descriptor.cli_install is not None
        assert isinstance(descriptor.cli_install.install, CallableStep)
        assert isinstance(descriptor.cli_install.uninstall, CallableStep)

    def test_provider_spec_required_fields(self) -> None:
        """PROVIDER_SPEC enforces required fields."""
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        with pytest.raises(AudiaGenticError, match="VAL-DESC-003"):
            PROVIDER_SPEC.load({})

    def test_provider_spec_defaults(self) -> None:
        """PROVIDER_SPEC applies defaults for optional fields."""
        data = {
            "provider_id": "test",
            "display_name": "Test",
            "execution_isolation_tier": "no-isolation",
        }
        resolved = PROVIDER_SPEC.load(data)
        assert resolved["access_mode"] == "cli"
        assert resolved["receive_lsp_mcp"] is True
        assert resolved["capabilities"] == ()

    def test_provider_spec_requires_valid_execution_isolation_tier(self) -> None:
        with pytest.raises(Exception, match="execution_isolation_tier"):
            PROVIDER_SPEC.build({
                "provider_id": "test",
                "display_name": "Test",
                "execution_isolation_tier": "unknown",
            })

    def test_rejects_invalid_mcp_launch_isolation_tier(self) -> None:
        with pytest.raises(Exception, match="mcp_launch_isolation_tier"):
            PROVIDER_SPEC.build({
                "provider_id": "test",
                "display_name": "Test",
                "execution_isolation_tier": "no-isolation",
                "mcp_launch_isolation_tier": "exclusive",
            })


class TestProvidersConfigDir:
    """Test provider config directory discovery."""

    def test_config_dir_exists(self) -> None:
        """Config directory exists."""
        config_dir = get_providers_config_dir()
        assert config_dir.is_dir()

    def test_config_dir_has_yaml_files(self) -> None:
        """Config directory has at least one YAML file."""
        config_dir = get_providers_config_dir()
        yaml_files = list(config_dir.glob("*.yaml")) + list(config_dir.glob("*.yml"))
        assert len(yaml_files) >= 1


class TestLoadProvidersFromDirectory:
    """Test bulk provider loading."""

    def test_load_all_providers(self) -> None:
        """Load all providers from config directory."""
        providers = load_providers_from_directory(get_providers_config_dir())
        expected = {"aider", "antigravity", "claude", "cline", "codex", "continue",
                     "copilot", "gemini", "goose", "local-openai", "opencode",
                     "openhands", "pi", "plandex", "qwen", "roo",
                     # CC53: minimal registered descriptors so these providers
                     # can own their harness_observability entries in their
                     # own file (previously only inventory rows in a central
                     # cross-provider Python list, no real descriptor at all).
                     "kilo", "zed", "crush",
                     # BR01: browser-driven ChatGPT provider descriptor.
                     "gpt-auto"}
        loaded = set(providers)
        assert expected == loaded, f"Missing: {expected - loaded}, Extra: {loaded - expected}"
        for descriptor in providers.values():
            assert isinstance(descriptor, ProviderDescriptor)
        assert descriptor.automation_capabilities is not None
        assert descriptor.execution_isolation_tier in {
                "full-isolation", "partial-isolation", "no-isolation"
            }

    def test_automation_capabilities_are_explicit_and_match_native_mechanics(self) -> None:
        providers = load_providers_from_directory(get_providers_config_dir())
        for provider_id, descriptor in providers.items():
            managed_mcp = descriptor.automation_capability("managed-mcp")
            assert (managed_mcp is not None) is (descriptor.mcp_config is not None), provider_id
        plugin = providers["opencode"].automation_capability("plugin-entry")
        assert plugin is not None
        assert plugin.payload_contract == "provider-plugin-entry-payload/v1"
        assert providers["opencode"].plugin_config is not None

    def test_supported_connectors_loads_from_yaml(self) -> None:
        """MO01: local-openai declares supported_connectors — a genuine repo fact
        (its only wire shape is the OpenAI-compatible REST surface)."""
        providers = load_providers_from_directory(get_providers_config_dir())
        assert providers["local-openai"].supported_connectors == ("openai-compatible",)

    def test_supported_connectors_defaults_empty(self) -> None:
        """MO01: an undeclared provider projects nothing — never a guessed default."""
        providers = load_providers_from_directory(get_providers_config_dir())
        assert providers["claude"].supported_connectors == ()

    def test_vendor_key_injection_defaults_empty_mapping(self) -> None:
        """MO01: values start empty and are populated only from MO09-verified evidence.

        Values are secrets.py scheme:locator reference strings, resolved only
        at the narrow consuming boundary — never a resolved secret.
        """
        providers = load_providers_from_directory(get_providers_config_dir())
        assert providers["claude"].vendor_key_injection == {}
        assert providers["pi"].vendor_key_injection["anthropic"] == "env:ANTHROPIC_API_KEY"
        assert providers["qwen"].vendor_key_injection["google"] == "env:GEMINI_API_KEY"


class TestManagedConfigTransports:
    """`transports` replaced the old boolean `remote` flag.

    It declares which entry shapes an adapter's registered reader/writer
    actually implement. That distinction matters: the previous flag conflated
    "the harness format supports remote" with "our writer emits remote", so
    goose declared remote support its writer could not serialize and silently
    dropped the url.
    """

    def test_every_mcp_adapter_declares_transports_explicitly(self) -> None:
        """There is no default: omission is a load error, not a stdio claim.

        The previous boolean silently treated "undeclared" as "stdio only",
        which is how eleven adapters stayed misdeclared. Absence must not
        manufacture a capability.
        """
        providers = load_providers_from_directory(get_providers_config_dir())
        for provider_id, descriptor in sorted(providers.items()):
            if descriptor.mcp_config is None:
                continue
            assert descriptor.mcp_config.transports, (
                f"{provider_id} has an mcp_config with no transports"
            )

    def test_transports_absent_from_domain_neutral_kinds(self) -> None:
        """hooks/lsp-config/plugins/models carry no transport concept."""
        providers = load_providers_from_directory(get_providers_config_dir())
        for provider_id, descriptor in sorted(providers.items()):
            for attr in ("hooks_config", "language_servers_config",
                         "model_config", "plugin_config"):
                spec = getattr(descriptor, attr, None)
                if spec is None:
                    continue
                assert not hasattr(spec, "transports"), (
                    f"{provider_id}.{attr} carries a transports field; the "
                    f"transport concept belongs to mcp-config-spec only"
                )

    def test_missing_transports_is_a_load_error(self) -> None:
        """An mcp mechanism without transports fails loudly."""
        from audiagentic.components.providers.descriptors.loader import (
            _build_mcp_config_spec,
        )
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        with pytest.raises(AudiaGenticError) as exc:
            _build_mcp_config_spec({
                "config_path": ".mcp.json",
                "reader": "audiagentic.foundation.mcp.json_format:read_mcp_json",
                "writer": "audiagentic.foundation.mcp.json_format:write_mcp_json",
                "remover": "audiagentic.foundation.mcp.json_format:remove_mcp_json",
            })
        assert exc.value.code == "VAL-PCAP-012"

    def test_http_declaration_survives_a_real_round_trip(self, tmp_path: Path) -> None:
        """Every provider claiming http must actually persist a url-form entry.

        This is a behavioural check, not a source grep: write a remote entry
        through the declared writer, read it back through the declared reader,
        and require the endpoint to survive. Goose previously declared remote
        support while its writer hardcoded ``type: "stdio"``, silently dropping
        the url — exactly what this catches.
        """
        from audiagentic.foundation.mcp import McpServerEntry

        providers = load_providers_from_directory(get_providers_config_dir())
        for provider_id, descriptor in sorted(providers.items()):
            spec = descriptor.mcp_config
            if spec is None or "http" not in spec.transports:
                continue

            target = tmp_path / provider_id / "config-under-test"
            target.parent.mkdir(parents=True, exist_ok=True)
            entry = McpServerEntry(
                name="round-trip",
                url="https://example.invalid/mcp/bank/",
                headers={"Authorization": "Bearer tok"},
                transport="http",
            )
            spec.writer(target, {"round-trip": entry})
            restored = spec.reader(target)

            assert "round-trip" in restored, (
                f"{provider_id} declares http but the entry vanished on read-back"
            )
            got = restored["round-trip"]
            assert got.is_remote, (
                f"{provider_id} declares http but the entry came back non-remote — "
                f"the writer likely serialized it as a stdio command"
            )
            assert got.url == "https://example.invalid/mcp/bank/", (
                f"{provider_id} declares http but the url did not survive: {got.url!r}"
            )

    def test_unknown_transport_is_a_load_error(self) -> None:
        """An unrecognised transport fails loudly rather than being ignored."""
        from audiagentic.components.providers.descriptors.loader import (
            _build_mcp_config_spec,
        )
        from audiagentic.foundation.contracts.errors import AudiaGenticError

        with pytest.raises(AudiaGenticError) as exc:
            _build_mcp_config_spec({
                "config_path": ".mcp.json",
                "reader": "audiagentic.foundation.mcp.json_format:read_mcp_json",
                "writer": "audiagentic.foundation.mcp.json_format:write_mcp_json",
                "remover": "audiagentic.foundation.mcp.json_format:remove_mcp_json",
                "transports": ["stdio", "carrier-pigeon"],
            })
        assert exc.value.code == "VAL-PCAP-012"
        assert "carrier-pigeon" in str(exc.value.details)

    def test_no_provider_still_uses_the_removed_remote_flag(self) -> None:
        """The boolean is gone; a stale `remote:` key must not silently no-op."""
        import yaml

        config_dir = get_providers_config_dir()
        offenders = []
        for path in sorted(config_dir.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for kind, entry in (data.get("capabilities") or {}).items():
                entries = entry if isinstance(entry, list) else [entry]
                for item in entries:
                    if not isinstance(item, dict):
                        continue
                    mechanism = item.get("mechanism") or {}
                    if isinstance(mechanism, dict) and "remote" in mechanism:
                        offenders.append(f"{path.name}:{kind}")
        assert not offenders, f"stale `remote:` key still present in {offenders}"


class TestLoaderResilience:
    """CC56: one bad provider descriptor must not crash the whole loader."""

    VALID_YAML = (
        "provider_id: test-valid\n"
        "display_name: Test Valid\n"
        "execution_isolation_tier: no-isolation\n"
    )
    # Missing required `display_name` — triggers VAL-DESC-003.
    INVALID_YAML = "provider_id: test-invalid\nexecution_isolation_tier: no-isolation\n"

    def test_invalid_descriptor_is_skipped_not_fatal(self, tmp_path) -> None:
        from audiagentic.components.providers.descriptors.loader import (
            clear_load_errors,
            get_load_errors,
        )

        (tmp_path / "valid.yaml").write_text(self.VALID_YAML, encoding="utf-8")
        (tmp_path / "invalid.yaml").write_text(self.INVALID_YAML, encoding="utf-8")

        clear_load_errors()
        try:
            providers = load_providers_from_directory(tmp_path)
            assert "test-valid" in providers
            assert "test-invalid" not in providers

            errors = get_load_errors()
            assert len(errors) == 1
            path, exc = errors[0]
            assert path.name == "invalid.yaml"
            assert "display_name" in str(exc)
        finally:
            clear_load_errors()

    def test_clear_load_errors_resets_the_collector(self, tmp_path) -> None:
        from audiagentic.components.providers.descriptors.loader import (
            clear_load_errors,
            get_load_errors,
        )

        (tmp_path / "invalid.yaml").write_text(self.INVALID_YAML, encoding="utf-8")

        clear_load_errors()
        try:
            load_providers_from_directory(tmp_path)
            assert get_load_errors()
            clear_load_errors()
            assert get_load_errors() == []
        finally:
            clear_load_errors()

    def test_provider_load_errors_surface_through_providers_api(self, tmp_path) -> None:
        """The operator-facing accessor (consumed by gateway_overview) reports
        skipped descriptors as (filename, truncated-message) pairs."""
        from audiagentic.components.providers.descriptors.loader import (
            clear_load_errors,
        )
        from audiagentic.components.providers.providers_api import (
            get_provider_load_errors,
        )

        (tmp_path / "invalid.yaml").write_text(self.INVALID_YAML, encoding="utf-8")

        clear_load_errors()
        try:
            load_providers_from_directory(tmp_path)
            errors = get_provider_load_errors()
            assert errors == [("invalid.yaml", errors[0][1])]
            assert "display_name" in errors[0][1]
        finally:
            clear_load_errors()
