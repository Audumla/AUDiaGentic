from __future__ import annotations

from tests.integration.lifecycle import harness


def test_project_component_ids_are_subset_of_all_components() -> None:
    all_ids = set(harness.component_ids())
    project_ids = set(harness.project_component_ids())
    assert project_ids <= all_ids


def test_required_and_create_if_missing_helpers_return_paths(tmp_path) -> None:
    project_ids = harness.project_component_ids()
    assert project_ids
    component_id = project_ids[0]
    required = harness.required_managed_paths(component_id, tmp_path)
    cim = harness.create_if_missing_paths(component_id, tmp_path)
    assert all(path.is_absolute() for path in required)
    assert all(path.is_absolute() for path in cim)


def test_lifecycle_harness_config_selects_expected_registry_partition() -> None:
    selection = harness.HARNESS_CONFIG["selection"]
    assert selection["scope"] == "project"
    assert selection["exclude_core"] is True

    expected = {
        component_id
        for component_id, descriptor in harness.all_descriptors().items()
        if descriptor.scope == "project" and not descriptor.core
    }
    assert set(harness.project_component_ids()) == expected
