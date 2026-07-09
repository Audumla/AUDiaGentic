from __future__ import annotations

from pathlib import Path

from audiagentic.commands.launch import (
    _mark_provider_launch_reconciled,
    _should_reconcile_providers_on_launch,
)
from audiagentic.foundation.features.state import set_component_state


def test_launch_reconciles_providers_when_no_state_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_RECONCILE_PROVIDERS_ON_LAUNCH", raising=False)

    assert _should_reconcile_providers_on_launch(tmp_path) is True


def test_launch_skips_provider_reconcile_when_feature_state_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_RECONCILE_PROVIDERS_ON_LAUNCH", raising=False)
    set_component_state(tmp_path, "providers", {"implementations": {"codex": {"enabled": True}}})

    assert _should_reconcile_providers_on_launch(tmp_path) is False


def test_launch_skips_provider_reconcile_after_stamp(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AUDIAGENTIC_RECONCILE_PROVIDERS_ON_LAUNCH", raising=False)
    _mark_provider_launch_reconciled(tmp_path)

    assert _should_reconcile_providers_on_launch(tmp_path) is False


def test_launch_provider_reconcile_env_override(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUDIAGENTIC_RECONCILE_PROVIDERS_ON_LAUNCH", "0")
    assert _should_reconcile_providers_on_launch(tmp_path) is False

    monkeypatch.setenv("AUDIAGENTIC_RECONCILE_PROVIDERS_ON_LAUNCH", "1")
    assert _should_reconcile_providers_on_launch(tmp_path) is True
