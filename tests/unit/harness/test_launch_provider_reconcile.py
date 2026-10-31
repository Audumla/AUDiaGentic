from __future__ import annotations

from pathlib import Path

from audiagentic.commands.launch import (
    _mark_provider_launch_reconciled,
    _should_reconcile_providers_on_launch,
)
from audiagentic.foundation.features.state import set_component_state


def test_launch_reconciles_providers_when_no_state_exists(tmp_path: Path) -> None:

    assert _should_reconcile_providers_on_launch(tmp_path) is True


def test_launch_skips_provider_reconcile_when_feature_state_exists(tmp_path: Path) -> None:
    set_component_state(tmp_path, "providers", {"implementations": {"codex": {"enabled": True}}})

    assert _should_reconcile_providers_on_launch(tmp_path) is False


def test_launch_skips_provider_reconcile_after_stamp(tmp_path: Path) -> None:
    _mark_provider_launch_reconciled(tmp_path)

    assert _should_reconcile_providers_on_launch(tmp_path) is False


def test_launch_provider_reconcile_setting_overrides_the_default(tmp_path: Path) -> None:
    settings = tmp_path / ".audiagentic" / "settings.yaml"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text("schema_version: 1\nlaunch:\n  reconcile_providers: never\n", encoding="utf-8")
    assert _should_reconcile_providers_on_launch(tmp_path) is False

    settings.write_text("schema_version: 1\nlaunch:\n  reconcile_providers: always\n", encoding="utf-8")
    _mark_provider_launch_reconciled(tmp_path)
    assert _should_reconcile_providers_on_launch(tmp_path) is True
