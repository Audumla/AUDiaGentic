from __future__ import annotations

from pathlib import Path

from audiagentic.components.agent_jobs.prompt_templates import load_prompt_template


def test_load_prompt_template_falls_back_to_packaged_descriptor(tmp_path: Path) -> None:
    text, path = load_prompt_template(
        tmp_path,
        tag="ag-review",
        provider_id="codex",
        template_name=None,
    )

    assert text is not None
    assert "review action is triggered" in text
    assert path is None
