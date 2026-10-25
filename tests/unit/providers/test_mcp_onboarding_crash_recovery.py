"""Crash-image proof for the provider-owned native MCP v2 transition."""

from __future__ import annotations

import json
import sys

import pytest

from audiagentic.components.project import project_api
from audiagentic.components.providers import providers_api
from audiagentic.components.providers.services.mcp import onboarding
from audiagentic.components.providers.services.mcp.managed_mcp_registry import (
    McpOwnershipRegistry,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("AUDIAGENTIC_COMPONENT_PROFILE", raising=False)
    return tmp_path


def _request(mid="crash-mcp", name="crash-mcp", *, command=None, secret=None, present=True):
    entry = (
        (
            providers_api.ManagedMcpEntry(
                managed_id=mid,
                name=name,
                command=command or sys.executable,
                env=(("SERVICE_TOKEN", secret),) if secret else (),
            ),
        )
        if present
        else ()
    )
    return providers_api.ManagedMcpRequest("crash-fixture", None, entry)


def _apply(root, request, provider="pi"):
    plan = providers_api.preflight_managed_mcp(root, provider, request=request)
    return providers_api.apply_managed_mcp(
        root, provider, request=request, expected_revision=plan["revision"]
    )


def _break_commit(monkeypatch):
    original = McpOwnershipRegistry.write_document

    def crash(self, data):
        if not data.get("prepared") and self.document().get("prepared"):
            raise OSError("injected crash between native publication and ownership/proofs commit")
        return original(self, data)

    monkeypatch.setattr(McpOwnershipRegistry, "write_document", crash)


@pytest.mark.parametrize("provider", ["pi", "codex", "opencode"])
def test_crash_after_native_before_registry_commit_replays_proven_post(root, monkeypatch, provider):
    request = _request(secret="PRIVATE_NATIVE_SECRET")
    spec, target = onboarding._context(root, provider)
    _break_commit(monkeypatch)
    with pytest.raises(OSError, match="injected crash"):
        _apply(root, request, provider)
    before = target.read_bytes(), target.stat().st_mtime_ns
    registry = McpOwnershipRegistry(root)
    pending = registry.document()["prepared"]
    assert pending
    row = next(iter(pending.values()))
    assert row["pre_hash"] == "absent"
    assert row["post_hash"] == onboarding.revision(target)
    assert "PRIVATE_NATIVE_SECRET" not in registry.path.read_text()
    assert "PRIVATE_NATIVE_SECRET" not in json.dumps(row)
    # Read-only preflight may virtually interpret the exact post-image, never commit it.
    state_before = registry.path.read_bytes(), registry.path.stat().st_mtime_ns
    recovered = providers_api.preflight_managed_mcp(root, provider, request=request)["changes"]
    assert recovered == [
        {"managed_id": "crash-mcp", "action": "configure", "updates_existing": False}
    ]
    assert state_before == (registry.path.read_bytes(), registry.path.stat().st_mtime_ns)
    monkeypatch.undo()
    assert _apply(root, request, provider)["ok"]
    assert before == (target.read_bytes(), target.stat().st_mtime_ns)
    assert not McpOwnershipRegistry(root).document().get("prepared")
    assert McpOwnershipRegistry(root).load()[f"{provider}/crash-fixture"] == {
        "crash-mcp": "crash-mcp"
    }
    registry_before = registry.path.read_bytes(), registry.path.stat().st_mtime_ns
    assert not _apply(root, request, provider)["changed"]
    assert registry_before == (registry.path.read_bytes(), registry.path.stat().st_mtime_ns)


def test_crash_before_native_publish_preserves_pre_image_and_retries(root, monkeypatch):
    request = _request()
    before_publish = onboarding._atomic_native_replace

    def crash(*_args):
        raise OSError("injected pre-native crash")

    monkeypatch.setattr(onboarding, "_atomic_native_replace", crash)
    with pytest.raises(OSError, match="pre-native crash"):
        _apply(root, request)
    registry = McpOwnershipRegistry(root)
    _, path = onboarding._context(root, "pi")
    assert not path.exists()
    assert next(iter(registry.document()["prepared"].values()))["pre_hash"] == "absent"
    current = registry.path.read_bytes()
    providers_api.preflight_managed_mcp(root, "pi", request=request)
    assert registry.path.read_bytes() == current
    monkeypatch.setattr(onboarding, "_atomic_native_replace", before_publish)
    assert _apply(root, request)["ok"]
    assert not registry.document().get("prepared")
    assert "crash-mcp" in onboarding._context(root, "pi")[0].reader(path)


def test_modified_post_image_blocks_recovery_without_overwrite(root, monkeypatch):
    request = _request()
    _break_commit(monkeypatch)
    with pytest.raises(OSError):
        _apply(root, request)
    _, path = onboarding._context(root, "pi")
    path.write_bytes(path.read_bytes() + b"\n ")
    before = path.read_bytes()
    monkeypatch.undo()
    with pytest.raises(AudiaGenticError) as exc:
        providers_api.preflight_managed_mcp(root, "pi", request=request)
    assert exc.value.code == "CON-MCPONB-001"
    assert path.read_bytes() == before
    assert McpOwnershipRegistry(root).document()["prepared"]


@pytest.mark.parametrize("change", ["add", "update", "rename", "remove"])
def test_changed_native_crash_replays_without_duplicate_mutation(root, monkeypatch, change):
    initial = _request(name="old-mcp", command=sys.executable)
    assert _apply(root, initial)["ok"]
    request = {
        "add": _request("second-mcp", "second-mcp"),
        "update": _request(name="old-mcp", command=sys.executable + "-new"),
        "rename": _request(name="new-mcp"),
        "remove": _request(present=False),
    }[change]
    # Addition must preserve earlier independent managed IDs in a full-scope request.
    if change == "add":
        request = providers_api.ManagedMcpRequest(
            "crash-fixture", None, (*initial.entries, *request.entries)
        )
    _break_commit(monkeypatch)
    with pytest.raises(OSError):
        _apply(root, request)
    _, path = onboarding._context(root, "pi")
    before = path.read_bytes(), path.stat().st_mtime_ns
    monkeypatch.undo()
    assert _apply(root, request)["ok"]
    assert before == (path.read_bytes(), path.stat().st_mtime_ns)
    rows = McpOwnershipRegistry(root).load()["pi/crash-fixture"]
    assert (
        rows
        == {
            "add": {"crash-mcp": "old-mcp", "second-mcp": "second-mcp"},
            "update": {"crash-mcp": "old-mcp"},
            "rename": {"crash-mcp": "new-mcp"},
            "remove": {},
        }[change]
    )


def test_malformed_or_retargeted_prepared_intent_is_refused(root):
    registry = McpOwnershipRegistry(root)
    invalid = registry.document()
    invalid["prepared"] = {
        "pi/crash-fixture": {
            "scope": "pi/crash-fixture",
            "provider_id": "pi",
            "target": "/tmp/foreign.json",
            "pre_hash": "absent",
            "post_hash": "a" * 64,
            "before_hash": "b" * 64,
            "owners_after": {},
            "proofs_after": {},
        }
    }
    from audiagentic.foundation.io import atomic_write_json

    atomic_write_json(registry.path, invalid)
    with pytest.raises(AudiaGenticError) as exc:
        providers_api.preflight_managed_mcp(root, "pi", request=_request())
    assert exc.value.code == "CON-PMCP-002"


def test_crash_after_registry_commit_before_owner_receipt_retains_operation_id(root, monkeypatch):
    # Simulate a caller-visible error after provider already committed native + proofs.
    original = providers_api.apply_managed_mcp
    intercepted = False

    def committed_then_exception(*args, **kwargs):
        nonlocal intercepted
        value = original(*args, **kwargs)
        if not intercepted:
            intercepted = True
            raise OSError("after-registry-commit-before-receipt")
        return value

    monkeypatch.setattr(providers_api, "apply_managed_mcp", committed_then_exception)
    first = project_api.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])
    assert not first["ok"] and first["phase"] == "needs_reconciliation"
    _, path = onboarding._context(root, "pi")
    original_bytes = path.read_bytes(), path.stat().st_mtime_ns
    monkeypatch.setattr(providers_api, "apply_managed_mcp", original)
    repeat = project_api.install_mcp(root, mcp_id="ag-planning", harness_ids=["pi"])
    assert repeat["ok"] and repeat["operation_id"] == first["operation_id"]
    assert original_bytes == (path.read_bytes(), path.stat().st_mtime_ns)
