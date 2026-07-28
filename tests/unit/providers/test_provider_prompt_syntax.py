from __future__ import annotations

from pathlib import Path

from audiagentic.components.providers.services.execution.prompt_syntax import load_prompt_syntax


def test_provider_syntax_loads_project_profile_overlay(tmp_path: Path) -> None:
    config = tmp_path / ".audiagentic" / "config" / "execution"
    config.mkdir(parents=True)
    (config / "prompt-syntax.yaml").write_text(
        "default-profile: compact\nprofiles:\n  compact:\n    skill-surfaces:\n      claude:\n        renderer: claude\n",
        encoding="utf-8",
    )

    syntax = load_prompt_syntax(tmp_path)

    assert syntax["skill-surfaces"]["claude"]["renderer"] == "claude"
    assert syntax["directive-aliases"]["agent"] == "provider"
