"""Unit tests: provider surface lifecycle observer event wiring.

The integration suite drives prune/apply directly because it runs without an
event bus, so it never exercised the observer's event→action mapping. This
suite covers that gap: it verifies the observer reacts to the right lifecycle
events. Regression guard for disable/enable falling through silently (the
ag-* tag blocks lingering in AGENTS.md after disabling agent-jobs).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.providers.surfaces import observer


@pytest.fixture()
def recorded(monkeypatch: pytest.MonkeyPatch) -> dict[str, list]:
    calls: dict[str, list] = {"apply": [], "prune": []}
    monkeypatch.setattr(
        observer,
        "operate_provider_surfaces",
        lambda root, mode: calls[mode].append(root),
    )
    return calls


@pytest.mark.parametrize(
    ("event_type", "expect_prune", "expect_apply"),
    [
        ("lifecycle.component.installed", False, True),
        ("lifecycle.component.enabled", False, True),
        ("lifecycle.component.uninstalled", True, True),
        ("lifecycle.component.disabled", True, True),
    ],
)
def test_observer_maps_events_to_actions(
    recorded: dict[str, list],
    event_type: str,
    expect_prune: bool,
    expect_apply: bool,
) -> None:
    root = Path("/tmp/project")
    observer._on_component_lifecycle(
        event_type, {"component_id": "agent-jobs", "project_root": root}, {}
    )

    assert (len(recorded["prune"]) == 1) is expect_prune
    assert (len(recorded["apply"]) == 1) is expect_apply
    if expect_prune:
        assert recorded["prune"] == [root]
    if expect_apply:
        assert recorded["apply"] == [root]


def test_observer_ignores_non_path_project_root(recorded: dict[str, list]) -> None:
    observer._on_component_lifecycle(
        "lifecycle.component.disabled",
        {"component_id": "agent-jobs", "project_root": "/tmp/project"},
        {},
    )
    assert recorded["prune"] == []
    assert recorded["apply"] == []


@pytest.mark.parametrize(
    "event_type",
    [
        "lifecycle.component.installed",
        "lifecycle.component.enabled",
        "lifecycle.component.disabled",
        "lifecycle.component.uninstalled",
        "lifecycle.component.config_changed",
    ],
)
def test_project_owner_reconciles_selection_for_lifecycle(monkeypatch, tmp_path, event_type):
    from audiagentic.components.project import onboarding_events

    calls = []
    monkeypatch.setattr(
        onboarding_events.project_api,
        "reconcile_mcp_bindings",
        lambda root: calls.append(root) or [],
    )
    onboarding_events._on_lifecycle(
        event_type, {"component_id": "coding-lsp", "project_root": tmp_path}, {}
    )
    assert calls == [tmp_path]
