from __future__ import annotations

import pytest

from audiagentic.foundation.config.harness import require_harness_endpoint
from audiagentic.foundation.config.local_runtime import local_provider_base_url


def test_local_provider_explicit_config_wins(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_LOCAL_PROVIDER_BASE_URL", "http://env:9000")  # no longer read
    assert local_provider_base_url("http://config:8000/") == "http://config:8000"


def test_harness_endpoint_is_the_configured_url():
    assert require_harness_endpoint({"endpoint": {"url": "http://models.internal:9000/v1/"}}) == "http://models.internal:9000/v1"


@pytest.mark.parametrize(
    "cfg,code",
    [
        ({}, "CFG-HCFG-002"),
        ({"endpoint": {}}, "CFG-HCFG-003"),
        ({"endpoint": {"url": "models.internal:9000"}}, "CFG-HCFG-004"),
    ],
)
def test_invalid_harness_endpoint_fails_closed(cfg, code):
    with pytest.raises(Exception) as excinfo:
        require_harness_endpoint(cfg)
    assert excinfo.value.code == code


def test_local_provider_url_ignores_the_removed_environment_variable(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_LOCAL_PROVIDER_BASE_URL", "http://env:9000")
    assert local_provider_base_url() == "https://api.openai.com"
