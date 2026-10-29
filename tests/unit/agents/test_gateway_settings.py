"""CFG09: gateway configuration comes from the machine-scope ``gateway`` settings section."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.helpers.gateway_settings import use_gateway_settings

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


@pytest.fixture(autouse=True)
def _cwd_is_a_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A git checkout as the working directory, so project-scope settings could apply if they were read."""
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True)
    monkeypatch.chdir(root)
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    return root


def test_settings_configure_the_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_gateway_settings(
        monkeypatch, tmp_path,
        port=18411, idle_grace_seconds=90, queue_backend="in-memory", implementation="standalone",
        console_trace={"mode": "full", "max_chars": 512}, dashboard={"recent_seconds": 600},
    )
    assert _configured_port() == 18411
    assert resolve_idle_grace_seconds() == 90.0
    assert create_work_queue() is not None
    assert client._resolve_implementation_id(None) == ("standalone", "settings")
    assert (_mode(), _max_body_chars()) == ("full", 512)
    assert recent_window_seconds() == 600


def test_defaults_without_settings() -> None:
    assert resolve_idle_grace_seconds() == 0.0
    assert _mode() == "summary"
    assert gateway_setting("console_trace.file", default="unset") == "unset"
    assert not load_retention_policy().available
    assert not load_watchdog_policy().available


def test_the_gateway_is_machine_scope_and_ignores_a_projects_own_settings(
    tmp_path: Path, _cwd_is_a_project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (_cwd_is_a_project / ".audiagentic").mkdir()
    (_cwd_is_a_project / ".audiagentic" / "settings.yaml").write_text(
        "schema_version: 1\ngateway:\n  port: 18499\n  implementation: automatic\n", encoding="utf-8",
    )
    assert resolve_settings().get("gateway.port") == 18499  # the project scope is valid configuration...
    assert gateway_setting("port") is None  # ...but a shared gateway never reads it
    use_gateway_settings(monkeypatch, tmp_path, port=18411)
    assert _configured_port() == 18411


def test_invalid_gateway_settings_fail_with_file_and_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    path = use_gateway_settings(monkeypatch, tmp_path, port=70000)
    with pytest.raises(AudiaGenticError) as raised:
        resolve_settings()
    assert str(path) in str(raised.value.details) or str(path) in str(raised.value)
    assert not load_retention_policy().available  # policies fail safe: purges off
    assert "gateway.retention policy is invalid" in caplog.text


def test_retention_and_watchdog_policies_come_from_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_gateway_settings(
        monkeypatch, tmp_path,
        retention={"purge_enabled": True, "minimum_archive_age_seconds": 60, "journal_retention_days": 7},
        watchdog={"activity_lease_seconds": 120, "policy_id": "tuned"},
    )
    retention = load_retention_policy()
    assert retention.available and retention.enabled and retention.journal_retention_days == 7
    watchdog = load_watchdog_policy()
    assert watchdog.available and watchdog.activity_lease_seconds == 120.0 and watchdog.policy_id == "tuned"


def test_schema_bounds_match_the_policy_code_limits() -> None:
    """The retention limits exist in the schema and in the loader; they must not drift apart."""
    from audiagentic.components.agents.gateway.operations import retention_policy as rp
    from audiagentic.foundation.paths.names import get_package_components_config_dir

    schema = json.loads(
        (get_package_components_config_dir() / "agents" / "settings" / "gateway.schema.json").read_text("utf-8")
    )["properties"]["retention"]["properties"]
    for key in ("timeline_max_bytes", "observation_max_bytes", "recovery_max_bytes", "console_trace_max_bytes"):
        assert schema[key]["maximum"] == rp._MAX_CONFIGURED_BYTES, key
    for key in ("request_history_limit", "max_batch_size"):
        assert schema[key]["maximum"] == rp._MAX_REQUEST_HISTORY_LIMIT, key
    assert schema["journal_retention_days"]["maximum"] == 3650
