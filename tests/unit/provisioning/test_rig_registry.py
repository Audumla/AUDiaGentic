from __future__ import annotations

from unittest.mock import patch

from audiagentic.runtime.rig import registry


def test_ensure_rig_state_adopts_live_server_when_registry_missing() -> None:
    with patch("audiagentic.runtime.rig.registry.read_rig_state", return_value=None), \
         patch("audiagentic.runtime.rig.registry._query_server_model", return_value="qwen3.5-9b-flash"), \
         patch("audiagentic.runtime.rig.registry._find_pid_listening_on_port", return_value=59172), \
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


def test_shutdown_rig_if_last_adopts_missing_registry_before_kill() -> None:
    with patch("audiagentic.runtime.rig.registry._live_client_count", return_value=0), \
         patch("audiagentic.runtime.rig.registry.read_rig_state", return_value=None), \
         patch(
             "audiagentic.runtime.rig.registry.adopt_rig_state",
             return_value={"pid": 59172, "port": 42001, "endpoint": "http://127.0.0.1:42001/v1", "model": "qwen3.5-9b-flash"},
         ), \
         patch("audiagentic.runtime.rig.registry._kill_pid") as mock_kill, \
         patch("audiagentic.runtime.rig.registry._clear_rig_state") as mock_clear:
        registry.shutdown_rig_if_last(42001)

    mock_kill.assert_called_once_with(59172)
    mock_clear.assert_called_once()
