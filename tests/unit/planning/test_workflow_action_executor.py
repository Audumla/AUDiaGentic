from __future__ import annotations

import pytest

from audiagentic.planning.app.services.workflow_action_executor import render


def test_render_preserves_typed_placeholder_values() -> None:
    task_ids = ["task-1", "task-2"]

    assert render("{task_ids}", {"task_ids": task_ids}) is task_ids


def test_render_formats_mixed_strings() -> None:
    assert render("prefix-{label}", {"label": "alpha"}) == "prefix-alpha"


def test_render_recurses_through_lists_and_dicts() -> None:
    result = render(
        {
            "refs": {
                "parent": "{parent_id}",
                "children": "{child_ids}",
            },
            "labels": ["{label}", "static"],
        },
        {
            "parent_id": "plan-1",
            "child_ids": ["task-1"],
            "label": "Package",
        },
    )

    assert result == {
        "refs": {
            "parent": "plan-1",
            "children": ["task-1"],
        },
        "labels": ["Package", "static"],
    }


def test_render_unknown_placeholder_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown placeholder"):
        render("{missing}", {})


def test_render_unknown_mixed_placeholder_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown placeholder"):
        render("prefix-{missing}", {})
