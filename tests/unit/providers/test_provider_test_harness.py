from __future__ import annotations

from tests.integration.providers import harness


def test_harness_policy_config_loads_known_provider_overrides() -> None:
    pi_policy = harness.policy_for("pi")
    assert pi_policy.use_project_root is True
    assert pi_policy.trust_install_probe is True

    plandex_policy = harness.policy_for("plandex")
    assert plandex_policy.docker_skip_reason

    roo_policy = harness.policy_for("roo")
    assert roo_policy.require_code_cli is True


def test_harness_provider_ids_matches_installable_registry() -> None:
    all_ids = set(harness.provider_ids())
    workflow_ids = set(harness.workflow_installable_provider_ids())
    assert workflow_ids == all_ids


def test_harness_package_manager_filter_is_data_driven() -> None:
    npm_ids = set(harness.provider_ids(package_manager="npm"))
    assert {"claude", "codex", "cline", "continue", "copilot", "gemini", "opencode", "qwen"} <= npm_ids


def test_harness_policy_entries_reference_real_installable_providers() -> None:
    installable_ids = set(harness.provider_ids())
    assert set(harness.PROVIDER_POLICIES) <= installable_ids


def test_non_installable_ids_partition_registry() -> None:
    installable_ids = set(harness.provider_ids())
    non_installable_ids = set(harness.non_installable_provider_ids())
    all_ids = set(harness.all_descriptors())
    assert installable_ids.isdisjoint(non_installable_ids)
    assert installable_ids | non_installable_ids == all_ids
