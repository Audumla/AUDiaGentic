"""Unavailable implicit browser discovery must not block unrelated providers."""
import copy
from pathlib import Path

import pytest
from tests.gpt_auto.test_greenfield_config_urls import valid_config

from audiagentic.components.providers.adapters.gpt_auto import config
from audiagentic.components.providers.services.config import provider_config
from audiagentic.foundation.contracts.errors import AudiaGenticError


def test_headless_machine_defers_implicit_browser_requirement_until_project_use(tmp_path, monkeypatch):
    defaults = copy.deepcopy(valid_config())
    defaults["browser"]["executable"] = "auto"
    monkeypatch.setattr(config, "_load_packaged_defaults", lambda: defaults)
    monkeypatch.setattr(config, "_load_machine_override", lambda *args: {})
    monkeypatch.setattr(config, "discover_browser_candidates", lambda: ())
    monkeypatch.setattr(config, "_check_gpt_auto_dependencies", lambda: None)

    config.validate_machine_gpt_auto_config()
    with pytest.raises(AudiaGenticError, match="browser.executable"):
        config.validate_project_gpt_auto_config(tmp_path)


def test_headless_machine_still_rejects_explicit_missing_browser_path(tmp_path: Path, monkeypatch):
    defaults = copy.deepcopy(valid_config())
    defaults["browser"]["executable"] = str(tmp_path / "absent-browser")
    monkeypatch.setattr(config, "_load_packaged_defaults", lambda: defaults)
    monkeypatch.setattr(config, "_load_machine_override", lambda *args: {})
    monkeypatch.setattr(config, "discover_browser_candidates", lambda: ())

    with pytest.raises(AudiaGenticError, match="browser.executable"):
        config.validate_machine_gpt_auto_config()
