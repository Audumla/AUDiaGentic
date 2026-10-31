from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.services.execution.prompt_syntax import load_prompt_syntax


def test_provider_syntax_loads_project_profile_overlay(tmp_path: Path) -> None:
    settings = tmp_path / ".audiagentic" / "settings.yaml"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        "schema_version: 1\nprompt-syntax:\n  default-profile: compact\n  profiles:\n    compact:\n"
        "      skill-surfaces:\n        claude:\n          renderer: claude\n",
        encoding="utf-8",
    )

    syntax = load_prompt_syntax(tmp_path)

    assert syntax["skill-surfaces"]["claude"]["renderer"] == "claude"
    assert syntax["directive-aliases"]["agent"] == "provider"
