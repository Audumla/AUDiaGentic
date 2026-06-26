"""Tests for Hindsight backend config export (HM01)."""
from __future__ import annotations

from audiagentic.components.memory.hindsight_export import (
    HindsightBackendConfig,
)


def test_build_backend_url():
    backend = HindsightBackendConfig(base_url="http://10.10.100.10:8888")
    assert backend.mcp_url == "http://10.10.100.10:8888/mcp"


def test_build_backend_url_already_has_mcp():
    backend = HindsightBackendConfig(base_url="http://10.10.100.10:8888/mcp")
    assert backend.mcp_url == "http://10.10.100.10:8888/mcp"


def test_headers_api_key_only():
    backend = HindsightBackendConfig(base_url="http://test", api_key="secret")
    headers = backend.headers()
    assert headers == {"Authorization": "Bearer secret"}


def test_headers_bank_id_only():
    backend = HindsightBackendConfig(base_url="http://test", bank_id="my-bank")
    headers = backend.headers()
    assert headers == {"X-Bank-Id": "my-bank"}


def test_headers_both():
    backend = HindsightBackendConfig(
        base_url="http://test", api_key="secret", bank_id="my-bank"
    )
    headers = backend.headers()
    assert headers == {
        "Authorization": "Bearer secret",
        "X-Bank-Id": "my-bank",
    }


def test_headers_neither():
    backend = HindsightBackendConfig(base_url="http://test")
    assert backend.headers() == {}


def test_no_provider_leak():
    """HindsightBackendConfig construction path references no provider id/path."""
    backend = HindsightBackendConfig(
        base_url="http://test",
        transport="http",
        api_key="k",
        bank_id="b",
        timeout_seconds=30,
        server_name="hindsight",
    )
    assert not hasattr(backend, "provider_id")
    assert not hasattr(backend, "config_path")


def test_no_legacy_backend_accessor():
    """No deprecated backend accessor shim remains."""
    import audiagentic.components.memory.hindsight_export as export

    assert not hasattr(export, "get_active_backend_config")
