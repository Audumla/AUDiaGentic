"""Provider reconciliation policy: mode and allowlist in settings, decisions as local state."""
from __future__ import annotations

import pytest
import yaml

from audiagentic.components.providers.services.config.provider_config import (
    get_reconciliation_policy,
    is_reconciliation_policy_configured,
    set_reconciliation_policy,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture(autouse=True)
def _isolated_user_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)


def _settings(root):
    path = root / ".audiagentic" / "settings.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else {}


def test_unset_policy_defaults_to_auto_and_unconfigured(tmp_path):
    assert get_reconciliation_policy(tmp_path) == {"mode": "auto"}
    assert is_reconciliation_policy_configured(tmp_path) is False


def test_set_allowlist_round_trips(tmp_path):
    saved = set_reconciliation_policy(
        tmp_path, mode="allowlist", allowed_providers=["codex", "claude"]
    )
    assert saved == {"mode": "allowlist", "allowed-providers": ["claude", "codex"]}

    assert get_reconciliation_policy(tmp_path) == saved
    assert is_reconciliation_policy_configured(tmp_path) is True
    assert _settings(tmp_path)["reconciliation"] == {"mode": "allowlist", "allowed-providers": ["claude", "codex"]}


def test_decisions_are_local_state_not_settings(tmp_path):
    saved = set_reconciliation_policy(
        tmp_path, mode="prompt", decided_providers=["codex", "claude", "codex"]
    )
    assert saved == {"mode": "prompt", "decided-providers": ["claude", "codex"]}
    assert "decided-providers" not in _settings(tmp_path)["reconciliation"]


def test_set_auto_mode_has_no_stale_lists(tmp_path):
    set_reconciliation_policy(
        tmp_path, mode="allowlist", allowed_providers=["codex"], decided_providers=["codex"]
    )
    saved = set_reconciliation_policy(tmp_path, mode="auto")
    assert saved == {"mode": "auto"}


def test_set_invalid_mode_raises_and_does_not_write(tmp_path):
    with pytest.raises(AudiaGenticError) as excinfo:
        set_reconciliation_policy(tmp_path, mode="bogus")
    assert excinfo.value.code == "VAL-PCFG-002"
    assert _settings(tmp_path) == {}


def test_settings_schema_rejects_an_invalid_mode(tmp_path):
    settings = tmp_path / ".audiagentic" / "settings.yaml"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("schema_version: 1\nreconciliation:\n  mode: bogus\n", encoding="utf-8")
    with pytest.raises(AudiaGenticError):
        get_reconciliation_policy(tmp_path)
