"""Provider reconciliation-policy storage (ON01).

Mirrors test_provider_config_loading.py's marker-file tolerance conventions:
an existing-but-empty providers.yaml (the installer's comment-only marker)
must behave the same as a missing file for the new policy helpers too.
"""
from __future__ import annotations

import pytest

from audiagentic.components.providers.services.config.provider_config import (
    get_reconciliation_policy,
    is_reconciliation_policy_configured,
    set_reconciliation_policy,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import load_yaml_file

_PATH_PARTS = (".audiagentic", "config", "runtime", "providers.yaml")


def _providers_yaml_path(root):
    path = root
    for part in _PATH_PARTS:
        path = path / part
    return path


def _write_marker(root) -> None:
    path = _providers_yaml_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Installation marker", encoding="utf-8")


def test_missing_file_defaults_to_auto_and_unconfigured(tmp_path):
    assert get_reconciliation_policy(tmp_path) == {"mode": "auto"}
    assert is_reconciliation_policy_configured(tmp_path) is False


def test_marker_only_file_defaults_to_auto_and_unconfigured(tmp_path):
    _write_marker(tmp_path)
    assert get_reconciliation_policy(tmp_path) == {"mode": "auto"}
    assert is_reconciliation_policy_configured(tmp_path) is False


def test_set_allowlist_round_trips(tmp_path):
    saved = set_reconciliation_policy(
        tmp_path, mode="allowlist", allowed_providers=["codex", "claude"]
    )
    assert saved == {"mode": "allowlist", "allowed-providers": ["claude", "codex"]}

    assert get_reconciliation_policy(tmp_path) == saved
    assert is_reconciliation_policy_configured(tmp_path) is True

    # Prove it's actually persisted, not just cached.
    on_disk = load_yaml_file(_providers_yaml_path(tmp_path))
    assert on_disk["reconciliation-policy"] == saved


def test_set_on_marker_only_file_preserves_contract_version(tmp_path):
    """Regression guard: patch_provider_config's comment-only-file gap must
    not be repeated here — a marker-file write must still end up with
    contract-version, not just {'reconciliation-policy': ...}."""
    _write_marker(tmp_path)
    set_reconciliation_policy(tmp_path, mode="auto")

    on_disk = load_yaml_file(_providers_yaml_path(tmp_path))
    assert on_disk["contract-version"] == "v1"
    assert on_disk["reconciliation-policy"] == {"mode": "auto"}


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
    assert not _providers_yaml_path(tmp_path).exists()


def test_schema_rejects_invalid_mode_directly(tmp_path):
    """The schema itself (not just the Python-level check) must reject an
    invalid mode, mirroring test_genuinely_invalid_config_still_fails."""
    from audiagentic.components.providers.services.config.provider_config import (
        load_provider_config,
    )

    path = _providers_yaml_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "contract-version: v1\nreconciliation-policy:\n  mode: bogus\nproviders: {}\n",
        encoding="utf-8",
    )
    with pytest.raises(AudiaGenticError) as excinfo:
        load_provider_config(tmp_path)
    assert excinfo.value.code == "VAL-PCFG-001"
