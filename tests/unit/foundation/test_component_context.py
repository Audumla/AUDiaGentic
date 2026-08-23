from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.components.project import project_api
from audiagentic.components.session import session_api
from audiagentic.components.providers.contracts.session_status import ProviderSessionInfo
from audiagentic.foundation.components import context as context_mod
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_sanitize_context_section_redacts_and_bounds_values() -> None:
    assert context_mod.sanitize_context_section(
        "source-control", {"branch": "main", "api_key": "secret"}
    ) == {"branch": "main"}

    with pytest.raises(AudiaGenticError, match="JSON-compatible"):
        context_mod.sanitize_context_section("source-control", {"bad": object()})


def test_project_context_reads_identity(tmp_path: Path) -> None:
    config = tmp_path / ".audiagentic" / "config"
    config.mkdir(parents=True)
    (config / "project.yaml").write_text(
        "project-id: example\nproject-name: Example\nworkflow-profile: standard\n",
        encoding="utf-8",
    )

    result = project_api.context(tmp_path)
    assert result["id"] == "example"
    assert result["name"] == "Example"
    assert result["root"] == str(tmp_path.resolve())


def test_session_context_excludes_provider_extensions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        session_api,
        "_resolve_session_info",
        lambda _root: ProviderSessionInfo(
            configured_model="qwen", model_profile_name="coding",
            extensions={"private": "not for prompts"},
        ),
    )

    result = session_api.context(tmp_path)
    assert result["model"] == "qwen"
    assert "extensions" not in result
