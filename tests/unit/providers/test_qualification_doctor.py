"""CFG07: doctor lists enabled surfaces that have no evidence for this platform."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from audiagentic.components.providers import doctor_checks
from audiagentic.components.providers.services.config.provider_config import set_provider_enabled
from audiagentic.components.providers.services.qualification import qualifier

FOREIGN = "linux-arm64"


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr("audiagentic.runtime.system.platform.release_platform_name", lambda: FOREIGN)
    monkeypatch.setattr(qualifier, "release_platform_name", lambda: FOREIGN)
    set_provider_enabled(tmp_path, "gpt-auto", enabled=True)
    return SimpleNamespace(project=tmp_path)


def test_an_unqualified_enabled_surface_is_a_warning_naming_the_fix(project) -> None:
    [result] = doctor_checks.check_qualification(project)
    assert result.status == "warn"
    assert "gpt-auto/gpt-auto-cdp (unqualified)" in result.message
    assert "audiagentic qualify" in result.fix


def test_a_qualified_surface_is_ok(project) -> None:
    qualifier.qualify("gpt-auto", "gpt-auto-cdp")
    [result] = doctor_checks.check_qualification(project)
    assert result.status == "ok", result.message


def test_the_override_is_reported(project) -> None:
    (project.project / ".audiagentic").mkdir(exist_ok=True)
    (project.project / ".audiagentic" / "settings.yaml").write_text(
        "schema_version: 1\nproviders:\n  gpt-auto:\n    allow-unqualified: true\n", encoding="utf-8")
    [result] = doctor_checks.check_qualification(project)
    assert result.status == "warn" and "explicit override" in result.message
