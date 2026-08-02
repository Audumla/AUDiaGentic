from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator

from audiagentic.components.providers.contracts.managed_mcp import (
    ManagedMcpEntry,
    ManagedMcpRequest,
    ManagedMcpResult,
)
from audiagentic.components.providers.services.capabilities import managed_mcp_family as family


def _descriptor(*, remote: bool = False):
    # `transports` names the entry shapes the adapter's reader/writer implement;
    # http is what allows a url-form entry to be written faithfully.
    transports = frozenset({"stdio", "http"}) if remote else frozenset({"stdio"})
    return SimpleNamespace(
        mcp_config=SimpleNamespace(transports=transports),
        automation_capability=lambda family_id: object() if family_id == "managed-mcp" else None,
    )


def _entry(*, remote: bool = False):
    if remote:
        return ManagedMcpEntry(
            managed_id="ag-hindsight",
            name="hindsight",
            url="https://example.invalid/mcp",
            transport="http",
        )
    return ManagedMcpEntry(
        managed_id="ag-hindsight",
        name="hindsight",
        command="hindsight-mcp",
    )


def _request(*, remote: bool = False, empty: bool = False):
    return ManagedMcpRequest(
        ownership_scope="memory/hindsight/hindsight",
        entries=() if empty else (_entry(remote=remote),),
    )


def test_descriptor_backed_provider_is_supported(monkeypatch, tmp_path):
    """Any provider with mcp_config in its descriptor is supported — no registrations."""
    monkeypatch.setattr(family, "get_descriptor", lambda _pid: _descriptor())
    result = family.manage_mcp_entries(
        tmp_path,
        "any-provider",
        mode="status",
        request=ManagedMcpRequest(ownership_scope="test/scope"),
    )
    assert result.supported is True


def test_no_mcp_config_is_unsupported(monkeypatch, tmp_path):
    """Provider without mcp_config returns supported=False."""
    monkeypatch.setattr(family, "get_descriptor", lambda _pid: SimpleNamespace(mcp_config=None))
    result = family.manage_mcp_entries(
        tmp_path,
        "no-mcp-provider",
        mode="status",
        request=ManagedMcpRequest(ownership_scope="test/scope"),
    )
    assert result.ok is False
    assert result.supported is False
    assert result.error_code == "RES-PREC-001"


def test_unknown_provider_and_unsupported_mode_are_safe(tmp_path):
    unknown = family.manage_mcp_entries(
        tmp_path, "no-such-provider", mode="status", request=_request(empty=True)
    )
    assert unknown.ok is False
    assert unknown.supported is False
    assert unknown.error_code == "RES-PREC-001"

    unsupported = family.manage_mcp_entries(
        tmp_path,
        "copilot",
        mode="plan",
        request=_request(empty=True),  # type: ignore[arg-type]
    )
    assert unsupported.ok is False
    assert unsupported.error_code == "CON-PREC-002"


def test_apply_returns_only_frozen_result_and_uses_scope(monkeypatch, tmp_path):
    monkeypatch.setattr(family, "get_descriptor", lambda _pid: _descriptor(remote=True))
    scopes = []
    monkeypatch.setattr(
        family,
        "sync_managed_provider_mcp_scope",
        lambda pid, root, scope, desired, managed_ids=None: (
            scopes.append(scope)
            or {
                "ok": True,
                "updated": ["hindsight"],
                "removed": [],
                "collisions": [],
                "auto_refreshed": True,
            }
        ),
    )
    monkeypatch.setattr(
        family,
        "mcp_ownership_registry",
        lambda _root: SimpleNamespace(
            load=lambda: {"copilot/memory/hindsight/hindsight": {"ag-hindsight": "hindsight"}}
        ),
    )

    result = family.manage_mcp_entries(
        tmp_path,
        "copilot",
        mode="apply",
        request=_request(remote=True),
    )
    assert scopes == ["copilot/memory/hindsight/hindsight"]
    assert result == ManagedMcpResult(
        ok=True,
        supported=True,
        provider_id="copilot",
        changed=True,
        managed_ids=("ag-hindsight",),
    )


def test_remote_entry_rejected_for_stdio_only_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(family, "get_descriptor", lambda _pid: _descriptor())
    result = family.manage_mcp_entries(
        tmp_path,
        "cline",
        mode="apply",
        request=_request(remote=True),
    )
    assert result.supported is False
    assert result.error_code == "CON-PMCP-001"


def test_serialized_contracts_match_concrete_schemas():
    contract_dir = Path(family.__file__).resolve().parents[2] / "contracts"
    request_schema = json.loads(
        (contract_dir / "provider-managed-mcp-payload.schema.json").read_text(encoding="utf-8")
    )
    result_schema = json.loads(
        (contract_dir / "provider-managed-mcp-result.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator(request_schema).validate(_request(remote=True).to_mapping())
    Draft202012Validator(result_schema).validate(
        ManagedMcpResult(ok=True, supported=True).to_mapping()
    )
