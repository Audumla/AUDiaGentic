"""Expanded content identity is independent of roots and rendering context."""

import hashlib
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway.admission.instructions import (
    ExpandedPrompt,
    expand_agent_prompt,
    materialize_agent_prompt,
    render_expanded_prompt,
)
from audiagentic.components.agents.models.prompt_definition import PromptDefinition
from audiagentic.foundation.contracts.errors import AudiaGenticError


def definition(prompt_id, *parts):
    return PromptDefinition.from_dict({"prompt_id": prompt_id, "content": list(parts)})


@pytest.fixture
def selected(tmp_path):
    main = definition(
        "main",
        {"kind": "include", "prompt_id": "included"},
        {"kind": "file", "path": "instructions.txt"},
        {"kind": "text", "text": "Task {prompt-body}"},
    )
    included = definition("included", {"kind": "text", "text": "Read {project.name}"})
    (tmp_path / "instructions.txt").write_text("Unicode café → {prompt-body}", encoding="utf-8")
    return main, included


def test_identity_is_exact_unrendered_utf8_and_cannot_be_forged():
    text = "café → {prompt-body}\n"
    prompt = ExpandedPrompt(text)
    assert prompt.content == text
    assert prompt.version == 1
    assert prompt.sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    with pytest.raises(TypeError):
        ExpandedPrompt(text, sha256="forged")
    with pytest.raises(FrozenInstanceError):
        prompt.content = "different"
    with pytest.raises(FrozenInstanceError):
        prompt.sha256 = "forged"
    with pytest.raises((TypeError, ValueError)):
        replace(prompt, sha256="forged")
    assert replace(prompt, content="different").sha256 == hashlib.sha256(b"different").hexdigest()


def test_different_roots_same_selected_content_have_same_identity(tmp_path, selected):
    main, included = selected
    other = tmp_path / "other"
    other.mkdir()
    (other / "instructions.txt").write_bytes((tmp_path / "instructions.txt").read_bytes())
    first = expand_agent_prompt(main, prompts=selected, config_root=tmp_path)
    second = expand_agent_prompt(main, prompts=selected, config_root=other)
    assert first == second
    assert first.content == "Read {project.name}\nUnicode café → {prompt-body}\nTask {prompt-body}"


def test_changed_include_and_file_content_each_change_digest(tmp_path, selected):
    main, included = selected
    first = expand_agent_prompt(main, prompts=selected, config_root=tmp_path)
    changed = definition("included", {"kind": "text", "text": "Changed include"})
    second = expand_agent_prompt(main, prompts=(main, changed), config_root=tmp_path)
    assert first.sha256 != second.sha256
    (tmp_path / "instructions.txt").write_text("Changed file", encoding="utf-8")
    third = expand_agent_prompt(main, prompts=(main, changed), config_root=tmp_path)
    assert second.sha256 != third.sha256


def test_unrelated_catalog_content_does_not_change_digest(tmp_path, selected):
    main, included = selected
    unrelated = definition("unrelated", {"kind": "file", "path": "absent.txt"})
    first = expand_agent_prompt(main, prompts=(*selected, unrelated), config_root=tmp_path)
    changed = definition("unrelated", {"kind": "text", "text": "Completely different"})
    second = expand_agent_prompt(main, prompts=(changed, included, main), config_root=tmp_path)
    assert first == second


def test_rendering_after_file_change_uses_frozen_content_without_reread(
    tmp_path, selected, monkeypatch
):
    main, included = selected
    expanded = expand_agent_prompt(main, prompts=selected, config_root=tmp_path)
    original_digest = expanded.sha256
    (tmp_path / "instructions.txt").write_text("Changed file", encoding="utf-8")

    def forbidden(*args, **kwargs):
        raise AssertionError("render reread a file")

    monkeypatch.setattr(Path, "read_text", forbidden)
    assert (
        render_expanded_prompt(
            expanded, template_context={"project": {"name": "Repo"}, "prompt-body": "BODY"}
        )
        == "Read Repo\nUnicode café → BODY\nTask BODY"
    )
    assert (
        render_expanded_prompt(
            expanded, template_context={"project": {"name": "Other"}, "prompt-body": "NEXT"}
        )
        == "Read Other\nUnicode café → NEXT\nTask NEXT"
    )
    assert expanded.sha256 == original_digest


@pytest.mark.parametrize(
    "case,code,details",
    [
        ("cycle", "VAL-AGW-110", {"prompt-id": "main"}),
        ("unknown", "RES-AGW-110", {"prompt-id": "main", "included-prompt-id": "missing"}),
        ("escape", "VAL-AGW-111", {"prompt-id": "main"}),
        ("unreadable", "RES-AGW-114", {"prompt-id": "main", "path": "absent.txt"}),
    ],
)
def test_expansion_and_materializer_preserve_errors(tmp_path, case, code, details):
    parts = {
        "cycle": {"kind": "include", "prompt_id": "main"},
        "unknown": {"kind": "include", "prompt_id": "missing"},
        "escape": {"kind": "file", "path": "../outside.txt"},
        "unreadable": {"kind": "file", "path": "absent.txt"},
    }
    main = definition("main", parts[case])
    for operation, extra in (
        (expand_agent_prompt, {}),
        (materialize_agent_prompt, {"template_context": {}}),
    ):
        with pytest.raises(AudiaGenticError) as caught:
            operation(main, prompts=(main,), config_root=tmp_path, **extra)
        assert caught.value.code == code
        assert caught.value.details == details
        if case == "unreadable":
            assert isinstance(caught.value.__cause__, OSError)


def test_permission_error_keeps_unreadable_error_and_cause(tmp_path, monkeypatch):
    main = definition("main", {"kind": "file", "path": "private.txt"})
    error = PermissionError("denied")

    def denied(*args, **kwargs):
        raise error

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(AudiaGenticError) as caught:
        expand_agent_prompt(main, prompts=(main,), config_root=tmp_path)
    assert caught.value.code == "RES-AGW-114"
    assert caught.value.__cause__ is error


def test_ordinary_materializer_bytes_and_empty_fragment_joining_unchanged(tmp_path):
    included = definition("included", {"kind": "text", "text": "Included {prompt-body}"})
    main = definition(
        "main",
        {"kind": "text", "text": ""},
        {"kind": "include", "prompt_id": "included"},
        {"kind": "text", "text": "\nTrailing\n"},
    )
    expanded = expand_agent_prompt(main, prompts=(main, included), config_root=tmp_path)
    assert expanded.content == "Included {prompt-body}\n\nTrailing\n"
    assert (
        materialize_agent_prompt(
            main,
            prompts=(main, included),
            config_root=tmp_path,
            template_context={"prompt-body": "BODY"},
        )
        == "Included BODY\n\nTrailing\n"
    )


def test_missing_placeholder_still_fails_during_render_not_expansion(tmp_path):
    main = definition("main", {"kind": "text", "text": "{missing.value}"})
    expanded = expand_agent_prompt(main, prompts=(main,), config_root=tmp_path)
    with pytest.raises(AudiaGenticError) as caught:
        render_expanded_prompt(expanded, template_context={})
    assert caught.value.code == "VAL-TPL-001"
