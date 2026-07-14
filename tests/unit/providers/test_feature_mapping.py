from __future__ import annotations

from audiagentic.components.providers.descriptors.base import (
    AgentFile,
    ProviderDescriptor,
)
from audiagentic.components.providers.descriptors.feature_mapping import (
    KIND_MCP,
    KIND_SKILLS,
    KIND_SURFACE,
    impl_features_for,
)
from audiagentic.foundation.features import registry as feature_registry
from audiagentic.foundation.features.base import FEATURE_SCOPE_IMPLEMENTATION
from audiagentic.foundation.toolchains.managed_config import ManagedConfigSpec


def _provider(provider_id: str = "x", **kwargs) -> ProviderDescriptor:
    return ProviderDescriptor(provider_id=provider_id, display_name=provider_id, **kwargs)


def _fake_mcp_spec() -> ManagedConfigSpec:
    return ManagedConfigSpec(
        config_path="x.json",
        reader=lambda p: {},
        writer=lambda p, e: None,
        remover=lambda p, k: False,
        refresh_mode="restart-required",
    )


def test_no_capabilities_yields_no_features() -> None:
    assert impl_features_for(_provider()) == []


def test_surface_unions_agent_files_and_instruction_file() -> None:
    descriptor = _provider(agent_files=(AgentFile(rel_path="AGENTS.md"),), instruction_file="QWEN.md")
    surfaces = {f.feature_id for f in impl_features_for(descriptor) if f.kind == KIND_SURFACE}
    assert surfaces == {"AGENTS.md", "QWEN.md"}


def test_surface_does_not_duplicate_instruction_file_already_in_agent_files() -> None:
    descriptor = _provider(agent_files=(AgentFile(rel_path="CLAUDE.md"),), instruction_file="CLAUDE.md")
    surfaces = [f.feature_id for f in impl_features_for(descriptor) if f.kind == KIND_SURFACE]
    assert surfaces == ["CLAUDE.md"]


def test_derived_features_are_implementation_scoped_to_the_provider() -> None:
    descriptor = _provider(provider_id="acme", skill_surface_path=".acme/skills/{tag}/SKILL.md")
    skills = [f for f in impl_features_for(descriptor) if f.kind == KIND_SKILLS]
    assert len(skills) == 1
    feature = skills[0]
    assert feature.scope == FEATURE_SCOPE_IMPLEMENTATION
    assert feature.implementation == "acme"
    assert feature.parent == "providers"


def test_real_providers_register_expected_impl_features() -> None:
    # all_descriptors() re-syncs implementation + feature registration for every
    # built-in provider; assert the derived impl-scoped features are present.
    from audiagentic.components.providers.descriptors import (
        registry as descriptor_registry,
    )

    descriptor_registry.all_descriptors()

    # claude declares MCP, skills, and surface files.
    assert feature_registry.get_implementation_feature("providers", "claude", KIND_MCP, KIND_MCP) is not None
    assert feature_registry.get_implementation_feature("providers", "claude", KIND_SKILLS, KIND_SKILLS) is not None
    assert "CLAUDE.md" in feature_registry.get_implementation_features("providers", "claude", KIND_SURFACE)
    # codex declares language-server support; aider declares none of mcp/skills.
    assert feature_registry.get_implementation_features("providers", "codex", "lsp-support")
    assert feature_registry.get_implementation_feature("providers", "aider", KIND_MCP, KIND_MCP) is None


def test_same_kind_across_providers_does_not_collide_in_registry() -> None:
    # Synthetic provider ids so we exercise the registry without disturbing the
    # real provider descriptors already registered in this process.
    for feature in impl_features_for(_provider("prov-a", mcp_config=_fake_mcp_spec())):
        feature_registry.register(feature)
    for feature in impl_features_for(_provider("prov-b", mcp_config=_fake_mcp_spec())):
        feature_registry.register(feature)

    a = feature_registry.get_implementation_feature("providers", "prov-a", KIND_MCP, KIND_MCP)
    b = feature_registry.get_implementation_feature("providers", "prov-b", KIND_MCP, KIND_MCP)
    assert a is not None and a.implementation == "prov-a"
    assert b is not None and b.implementation == "prov-b"
