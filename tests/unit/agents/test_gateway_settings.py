"""CFG09: gateway configuration comes from the ``gateway`` settings section."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.agents.gateway import client
from audiagentic.components.agents.gateway.operations.retention_policy import load_retention_policy
from audiagentic.components.agents.gateway.queue.backend_factory import create_work_queue
from audiagentic.components.agents.gateway.queue.watchdog_policy import load_watchdog_policy
from audiagentic.components.agents.gateway.service.bootstrap import _configured_port
from audiagentic.components.agents.gateway.service.dashboard import recent_window_seconds
from audiagentic.components.agents.gateway.service.lifecycle import resolve_idle_grace_seconds
from audiagentic.components.agents.gateway.session.console_trace import _max_body_chars, _mode
from audiagentic.components.agents.gateway.settings import gateway_setting
from audiagentic.foundation.config.settings import resolve_settings
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def user_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Write the user settings file; legacy env vars and policy files start absent."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    for name in (
        "PORT", "IDLE_GRACE_SECONDS", "QUEUE_BACKEND", "MODE", "EMBEDDED_ALLOW", "CONSOLE_TRACE",
        "CONSOLE_TRACE_MAX_CHARS", "DASHBOARD_RECENT_SECONDS", "RETENTION_POLICY", "WATCHDOG_POLICY",
    ):
        monkeypatch.delenv(f"AUDIAGENTIC_GATEWAY_{name}", raising=False)
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "xdg" / "audiagentic" / "settings.yaml"
    path.parent.mkdir(parents=True)

    def write(gateway_yaml: str) -> Path:
        path.write_text("schema_version: 1\ngateway:\n" + gateway_yaml, encoding="utf-8")
        return path

    return write


def test_settings_configure_the_gateway(user_settings) -> None:
    user_settings(
        "  port: 18411\n  idle_grace_seconds: 90\n  queue_backend: in-memory\n  implementation: standalone\n"
        "  embedded_with_live_shared_owner: warn\n"
        "  console_trace: {mode: full, max_chars: 512}\n  dashboard: {recent_seconds: 600}\n"
    )
    assert _configured_port() == 18411
    assert resolve_idle_grace_seconds() == 90.0
    assert create_work_queue() is not None
    assert client._resolve_implementation_id(None) == ("standalone", "settings")
    assert client._resolve_embedded_coexistence_policy(None) == "warn"
    assert (_mode(), _max_body_chars()) == ("full", 512)
    assert recent_window_seconds() == 600


def test_legacy_env_overrides_settings(user_settings, monkeypatch: pytest.MonkeyPatch) -> None:
    user_settings("  port: 18411\n  implementation: standalone\n")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_PORT", "18412")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_MODE", "embedded")
    assert _configured_port() == 18412
    assert client._resolve_implementation_id(None) == ("embedded", "env-override")


def test_defaults_without_settings(user_settings) -> None:
    user_settings("  {}\n")
    assert resolve_idle_grace_seconds() == 0.0
    assert _mode() == "summary"
    assert gateway_setting("console_trace.file", default="unset") == "unset"
    assert not load_retention_policy().available
    assert not load_watchdog_policy().available


def test_invalid_gateway_settings_fail_with_file_and_key(user_settings, caplog: pytest.LogCaptureFixture) -> None:
    path = user_settings("  port: 70000\n")
    with pytest.raises(AudiaGenticError) as raised:
        resolve_settings()
    assert str(path) in str(raised.value.details) or str(path) in str(raised.value)
    assert not load_retention_policy().available  # policies fail safe: purges off
    assert "gateway.retention policy is invalid" in caplog.text


def test_policies_from_settings_match_the_legacy_file_digest(
    user_settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy = tmp_path / "legacy-retention.json"
    legacy.write_text(json.dumps({"purge-enabled": True, "minimum-archive-age-seconds": 60,
                                  "journal-retention-days": 7}), encoding="utf-8")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY", str(legacy))
    from_file = load_retention_policy()
    monkeypatch.delenv("AUDIAGENTIC_GATEWAY_RETENTION_POLICY")

    user_settings(
        "  retention: {purge_enabled: true, minimum_archive_age_seconds: 60, journal_retention_days: 7}\n"
        "  watchdog: {activity_lease_seconds: 120, policy_id: tuned}\n"
    )
    from_settings = load_retention_policy()
    assert from_settings.available and from_settings.enabled and from_settings.journal_retention_days == 7
    assert from_settings.digest == from_file.digest
    watchdog = load_watchdog_policy()
    assert watchdog.available and watchdog.activity_lease_seconds == 120.0 and watchdog.policy_id == "tuned"


def test_settings_and_legacy_default_policy_file_are_ambiguous(
    user_settings, tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    user_settings("  watchdog: {activity_lease_seconds: 120}\n")
    legacy = tmp_path / "home" / ".audiagentic" / "gateway-watchdog.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}", encoding="utf-8")
    policy = load_watchdog_policy()
    assert not policy.available and policy.policy_id == "invalid"
    assert "gateway.watchdog policy is invalid" in caplog.text  # an operator can see why
    legacy.unlink()
    assert load_watchdog_policy().available
