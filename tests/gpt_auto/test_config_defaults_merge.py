"""GP20: gpt-auto's three-tier-ready config loader (packaged defaults +
project overlay). Covers deep_merge()'s recursive/replace semantics and
GptAutoConfig.from_project_dict()'s resolution against defaults.yaml."""

from __future__ import annotations

from audiagentic.components.providers.adapters.gpt_auto.config import (
    GptAutoConfig,
    deep_merge,
)


def test_deep_merge_recurses_into_nested_dicts_without_dropping_siblings() -> None:
    base = {"a": 1, "nested": {"x": 1, "y": 2}}
    override = {"nested": {"y": 20}}

    merged = deep_merge(base, override)

    assert merged == {"a": 1, "nested": {"x": 1, "y": 20}}


def test_deep_merge_replaces_lists_wholesale_not_concatenates() -> None:
    base = {"selectors": ["a", "b"]}
    override = {"selectors": ["c"]}

    merged = deep_merge(base, override)

    assert merged == {"selectors": ["c"]}


def test_deep_merge_does_not_mutate_inputs() -> None:
    base = {"nested": {"x": 1}}
    override = {"nested": {"x": 2}}

    deep_merge(base, override)

    assert base == {"nested": {"x": 1}}
    assert override == {"nested": {"x": 2}}


def test_from_project_dict_resolves_a_sparse_overlay_specifying_only_project_url() -> None:
    """The core GP20 acceptance criterion: a project overlay specifying only
    project-url (plus the still-required contract-version) resolves to a
    complete, valid GptAutoConfig via packaged defaults."""
    overlay = {
        "settings": {
            "contract-version": "v1",
            "project-url": "https://chatgpt.com/g/g-p-test-project",
        }
    }

    config = GptAutoConfig.from_project_dict(overlay)

    assert config.project_url == "https://chatgpt.com/g/g-p-test-project"
    # Values not mentioned in the overlay come from defaults.yaml.
    assert config.browser.remote_debugging_port == 9222
    assert config.turn.response_timeout_seconds == 3600
    assert config.workflow.policy("response-complete").all_of


def test_from_project_dict_overlay_override_wins_over_defaults() -> None:
    overlay = {
        "settings": {
            "contract-version": "v1",
            "project-url": "https://chatgpt.com/g/g-p-test-project",
            "turn": {"response-timeout-seconds": 60},
        }
    }

    config = GptAutoConfig.from_project_dict(overlay)

    assert config.turn.response_timeout_seconds == 60
    # Sibling turn fields not overridden still come from defaults.
    assert config.turn.poll_interval_seconds == 1
