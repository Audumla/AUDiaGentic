from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from audiagentic.components.memory.hindsight.matrix import HINDSIGHT_RECIPE_MATRIX
from audiagentic.components.memory.hindsight.plugin_definition import HindsightPluginDefinition


def test_claude_plugin_definition_validates_schema():
    row = next(item for item in HINDSIGHT_RECIPE_MATRIX if item.provider_id == "claude")
    definition = HindsightPluginDefinition.from_row(row)
    schema_path = Path(__file__).resolve().parents[3] / (
        "src/audiagentic/config/components/memory/hindsight-plugin-definition.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(definition.to_mapping())
    assert definition.settings_path is not None
