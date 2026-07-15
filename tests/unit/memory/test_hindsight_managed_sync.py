from __future__ import annotations

from audiagentic.components.memory.hindsight.export import HindsightBackendConfig
from audiagentic.components.memory.hindsight.mcp_recipe import (
    build_hindsight_managed_entry,
    hindsight_ownership_scope,
)


def test_stdio_family_payload_is_serializable_and_scoped():
    backend = HindsightBackendConfig(
        base_url="http://localhost:8888", api_key="secret", bank_id="bank",
        transport="stdio", server_name="hindsight",
    )
    entry = build_hindsight_managed_entry(backend)
    assert entry.managed_id == "ag-hindsight"
    assert entry.name == "hindsight"
    assert entry.command == "hindsight-mcp"
    assert entry.args == ("--base-url", "http://localhost:8888")
    assert dict(entry.env) == {"HINDSIGHT_API_KEY": "secret", "HINDSIGHT_BANK_ID": "bank"}
    assert hindsight_ownership_scope(backend) == "memory/hindsight/hindsight"


def test_remote_family_payload_uses_transport_not_provider_format():
    backend = HindsightBackendConfig(
        base_url="https://example.invalid", transport="http", server_name="memory",
    )
    entry = build_hindsight_managed_entry(backend)
    assert entry.transport == "http"
    assert entry.url == "https://example.invalid/mcp"
