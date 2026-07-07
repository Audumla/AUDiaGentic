from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

from audiagentic.runtime.rig import registry


@contextmanager
def _fake_lock():
    yield


def test_ensure_rig_state_adopts_live_server_when_registry_missing() -> None:
    with patch("audiagentic.runtime.rig.registry.read_rig_state", return_value=None), \
         patch("audiagentic.runtime.rig.registry._query_server_model", return_value="qwen3.5-9b-flash"), \
         patch("audiagentic.runtime.rig.registry.find_pid_on_port", return_value=59172), \
         patch("audiagentic.runtime.rig.registry.write_rig_state") as mock_write:
        state = registry.ensure_rig_state(42001, model="qwen3.5-9b-flash")

    assert state == {
        "pid": 59172,
        "port": 42001,
        "endpoint": "http://127.0.0.1:42001/v1",
        "model": "qwen3.5-9b-flash",
    }
    mock_write.assert_called_once_with(
        59172,
        42001,
        "http://127.0.0.1:42001/v1",
        "qwen3.5-9b-flash",
    )


def test_shutdown_rig_if_last_adopts_missing_registry_before_kill(tmp_path) -> None:
    with patch("audiagentic.runtime.rig.registry.rig_start_lock", _fake_lock), \
         patch("audiagentic.runtime.rig.registry._clients_dir", return_value=tmp_path / "clients"), \
         patch("audiagentic.runtime.rig.registry._live_client_count", return_value=0), \
         patch("audiagentic.runtime.rig.registry.read_rig_state", return_value=None), \
         patch(
             "audiagentic.runtime.rig.registry.adopt_rig_state",
             return_value={"pid": 59172, "port": 42001, "endpoint": "http://127.0.0.1:42001/v1", "model": "qwen3.5-9b-flash"},
         ), \
         patch("audiagentic.runtime.rig.registry.kill_pid") as mock_kill, \
         patch("audiagentic.runtime.rig.registry._clear_rig_state") as mock_clear:
        registry.shutdown_rig_if_last(42001)

    mock_kill.assert_called_once_with(59172)
    mock_clear.assert_called_once()


def test_shutdown_rig_if_last_keeps_rig_while_clients_remain(tmp_path) -> None:
    with patch("audiagentic.runtime.rig.registry.rig_start_lock", _fake_lock), \
         patch("audiagentic.runtime.rig.registry._clients_dir", return_value=tmp_path / "clients"), \
         patch("audiagentic.runtime.rig.registry._live_client_count", return_value=1), \
         patch("audiagentic.runtime.rig.registry.kill_pid") as mock_kill:
        registry.shutdown_rig_if_last(42001)

    mock_kill.assert_not_called()


def test_shutdown_serializes_under_start_lock(tmp_path) -> None:
    entered: list[str] = []

    @contextmanager
    def _tracking_lock():
        entered.append("locked")
        yield

    with patch("audiagentic.runtime.rig.registry.rig_start_lock", _tracking_lock), \
         patch("audiagentic.runtime.rig.registry._clients_dir", return_value=tmp_path / "clients"), \
         patch("audiagentic.runtime.rig.registry._live_client_count", return_value=1):
        registry.shutdown_rig_if_last(42001)

    assert entered == ["locked"]


def test_adopt_refuses_model_mismatch() -> None:
    with patch("audiagentic.runtime.rig.registry._query_server_model", return_value="other-model"), \
         patch("audiagentic.runtime.rig.registry.find_pid_on_port", return_value=59172), \
         patch("audiagentic.runtime.rig.registry.write_rig_state") as mock_write:
        state = registry.adopt_rig_state(42001, model="qwen3.5-9b-flash")

    assert state is None
    mock_write.assert_not_called()


def test_write_rig_state_is_atomic_and_readable(tmp_path) -> None:
    with patch("audiagentic.runtime.rig.registry._rig_runtime_dir", return_value=tmp_path):
        registry.write_rig_state(123, 42001, "http://127.0.0.1:42001/v1", "m")
        import json

        payload = json.loads((tmp_path / "rig.json").read_text(encoding="utf-8"))

    assert payload["pid"] == 123
    assert payload["model"] == "m"
    # no leftover temp file from the atomic replace
    assert not (tmp_path / "rig.json.tmp").exists()
