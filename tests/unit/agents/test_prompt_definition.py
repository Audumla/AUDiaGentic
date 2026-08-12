from __future__ import annotations

import pytest

from audiagentic.components.agents.models.prompt_definition import PromptDefinition, PromptTextPart


def test_prompt_definition_round_trips_and_is_deeply_immutable() -> None:
    source = {"type": "object", "properties": {"x": {"type": "string"}}}
    prompt = PromptDefinition("p", "test", (PromptTextPart("be useful"),), source)
    source["properties"]["x"]["type"] = "number"
    assert prompt.to_dict()["input_schema"]["properties"]["x"]["type"] == "string"
    with pytest.raises(TypeError):
        prompt.input_schema["new"] = True  # type: ignore[index]


def test_prompt_definition_accepts_yaml_field_aliases() -> None:
    prompt = PromptDefinition.from_dict({"prompt-id": "p", "system_prompt": "x"})
    assert prompt.prompt_id == "p"
    assert prompt.content == (PromptTextPart("x"),)
