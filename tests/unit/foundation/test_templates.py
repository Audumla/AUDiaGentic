"""Tests for foundation/templates.py — dotted-path template rendering."""
from __future__ import annotations

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.templates import render_template


class TestDottedPathLookup:
    """Verify {dotted.path} resolution against nested context dicts."""

    def test_single_segment(self) -> None:
        assert render_template("{id}", {"id": "abc123"}) == "abc123"

    def test_two_level_dotted_path(self) -> None:
        result = render_template(
            "{event.payload}",
            {"event": {"payload": "hello"}},
        )
        assert result == "hello"

    def test_three_level_dotted_path(self) -> None:
        result = render_template(
            "{event.payload.id}",
            {"event": {"payload": {"id": "evt-42"}}},
        )
        assert result == "evt-42"

    def test_deep_nested_path(self) -> None:
        ctx = {
            "metadata": {
                "subject": {
                    "type": "plan_item",
                    "id": "CI01",
                }
            }
        }
        assert render_template("{metadata.subject.id}", ctx) == "CI01"

    def test_multiple_placeholders(self) -> None:
        ctx = {
            "event": {"payload": {"id": "evt-1"}},
            "job": {"id": "job-99"},
        }
        result = render_template(
            "Event {event.payload.id} for job {job.id}",
            ctx,
        )
        assert result == "Event evt-1 for job job-99"


class TestHyphenatedKeySyntax:
    """Verify that hyphenated keys work in dotted paths."""

    def test_hyphenated_flat_key(self) -> None:
        result = render_template(
            "{project-root}",
            {"project-root": "/home/user/proj"},
        )
        assert result == "/home/user/proj"

    def test_hyphenated_nested_segment(self) -> None:
        ctx = {
            "metadata": {"correlation-id": "corr-abc"},
        }
        result = render_template("{metadata.correlation-id}", ctx)
        assert result == "corr-abc"

    def test_multiple_hyphenated_keys(self) -> None:
        ctx = {
            "subject": {"plan-item-id": "CI01"},
            "project-root": "/repo",
        }
        result = render_template(
            "{subject.plan-item-id} at {project-root}",
            ctx,
        )
        assert result == "CI01 at /repo"


class TestTypedWholePlaceholderRendering:
    """Verify non-string values are converted via str()."""

    def test_integer_value(self) -> None:
        assert render_template("{count}", {"count": 42}) == "42"

    def test_float_value(self) -> None:
        result = render_template("{score}", {"score": 3.14})
        assert result == "3.14"

    def test_boolean_value(self) -> None:
        assert render_template("{flag}", {"flag": True}) == "True"

    def test_none_value_replaces_to_empty(self) -> None:
        assert render_template("prefix-{opt}-suffix", {"opt": None}) == "prefix--suffix"


class TestMissingKeyError:
    """Verify VAL-TPL-001 is raised for missing paths."""

    def test_missing_flat_key_raises(self) -> None:
        with pytest.raises(AudiaGenticError) as exc_info:
            render_template("{missing}", {"id": "abc"})
        err = exc_info.value
        assert err.code == "VAL-TPL-001"
        assert "'missing'" in err.message
        assert "available top-level keys:" in err.message
        assert "id" in err.message

    def test_missing_nested_key_raises(self) -> None:
        ctx = {"event": {"payload": {}}}
        with pytest.raises(AudiaGenticError) as exc_info:
            render_template("{event.payload.id}", ctx)
        err = exc_info.value
        assert err.code == "VAL-TPL-001"
        assert "'event.payload.id'" in err.message

    def test_top_level_key_missing_in_nested_path(self) -> None:
        ctx = {"job": {"id": "j1"}}
        with pytest.raises(AudiaGenticError) as exc_info:
            render_template("{trigger.id}", ctx)
        err = exc_info.value
        assert err.code == "VAL-TPL-001"
        assert "'trigger.id'" in err.message
        assert "job" in err.message

    def test_error_details_contain_path_and_keys(self) -> None:
        with pytest.raises(AudiaGenticError) as exc_info:
            render_template("{foo}", {"a": 1, "b": 2})
        assert exc_info.value.details == {  # type: ignore[attr-defined]
            "path": "foo",
            "available_keys": ["a", "b"],
        }


class TestNestedListAndDictRendering:
    """Verify complex values (lists/dicts) are JSON-serialized."""

    def test_dict_value_serialized(self) -> None:
        import json
        ctx = {"meta": {"tags": {"a": 1, "b": 2}}}
        result = render_template("{meta.tags}", ctx)
        assert json.loads(result) == {"a": 1, "b": 2}

    def test_list_value_serialized(self) -> None:
        import json
        ctx = {"items": ["x", "y", "z"]}
        result = render_template("{items}", ctx)
        assert json.loads(result) == ["x", "y", "z"]

    def test_nested_dict_at_leaf(self) -> None:
        import json
        ctx = {"config": {"settings": {"timeout": 30}}}
        result = render_template("{config.settings}", ctx)
        assert json.loads(result) == {"timeout": 30}


class TestMixedStringFormatting:
    """Verify mixed literal text + placeholders works correctly."""

    def test_literal_text_with_placeholders(self) -> None:
        ctx = {"name": "Alice", "event": {"payload": {"id": "e1"}}}
        result = render_template(
            "Hello {name}, processing {event.payload.id}",
            ctx,
        )
        assert result == "Hello Alice, processing e1"

    def test_no_placeholders_passes_through(self) -> None:
        assert render_template("plain text only", {}) == "plain text only"

    def test_multiline_template(self) -> None:
        ctx = {"job": {"id": "j-1"}}
        template = "Task:\n  Job: {job.id}\nEnd."
        result = render_template(template, ctx)
        assert result == "Task:\n  Job: j-1\nEnd."


class TestWorkflowActionsRenderCompatibility:
    """Confirm existing workflow.actions.render callers are not affected."""

    def test_workflow_render_not_affected_by_module_import(self) -> None:
        from audiagentic.foundation.workflow.actions import render as wf_render
        result = wf_render("{key}", {"key": "val"})
        assert result == "val"

    def test_workflow_render_typed_whole_placeholder(self) -> None:
        from audiagentic.foundation.workflow.actions import render as wf_render
        result = wf_render("{count}", {"count": 42})
        assert result == 42

    def test_workflow_render_mixed_string(self) -> None:
        from audiagentic.foundation.workflow.actions import render as wf_render
        result = wf_render("prefix-{key}-suffix", {"key": "x"})
        assert result == "prefix-x-suffix"

    def test_workflow_render_list_recursive(self) -> None:
        from audiagentic.foundation.workflow.actions import render as wf_render
        result = wf_render(["{a}", "{b}"], {"a": 1, "b": 2})
        assert result == [1, 2]

    def test_dotted_template_is_separate_from_workflow_render(self) -> None:
        ctx = {"event": {"payload": {"id": "e1"}}}
        t_result = render_template("{event.payload.id}", ctx)
        assert t_result == "e1"


class TestPromptTemplateBackwardCompatibility:
    """Ensure prompt_templates.render_prompt_template still works for flat keys."""

    def test_flat_keys(self) -> None:
        from audiagentic.components.agent_jobs.prompt_templates import (
            render_prompt_template,
        )
        result = render_prompt_template(
            "Job {id} provider {provider}",
            {"id": "j1", "provider": "openai"},
        )
        assert result == "Job j1 provider openai"

    def test_hyphenated_flat_keys(self) -> None:
        from audiagentic.components.agent_jobs.prompt_templates import (
            render_prompt_template,
        )
        result = render_prompt_template(
            "{project-root}/{context-path}",
            {"project-root": "/repo", "context-path": "/ctx.md"},
        )
        assert result == "/repo//ctx.md"

    def test_none_value_stripped(self) -> None:
        from audiagentic.components.agent_jobs.prompt_templates import (
            render_prompt_template,
        )
        result = render_prompt_template(
            "prefix-{opt}-suffix",
            {"opt": None},
        )
        assert result == "prefix--suffix"

    def test_dotted_path_in_prompt_template(self) -> None:
        from audiagentic.components.agent_jobs.prompt_templates import (
            render_prompt_template,
        )
        result = render_prompt_template(
            "{subject.plan-item-id}",
            {"subject": {"plan-item-id": "CI01"}},
        )
        assert result == "CI01"
