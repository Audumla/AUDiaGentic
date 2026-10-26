"""Admission placement is constructed under the existing grant/revoke lock."""
from __future__ import annotations

import json
import multiprocessing
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from audiagentic.components.agents.gateway.node import authority as module
from audiagentic.components.agents.gateway.node.authority import NodeGrantAuthority
from audiagentic.components.agents.gateway.node.placement import NodeAdmissionPlacement
from audiagentic.components.agents.gateway.service.contract import GATEWAY_SERVICE_KEY
from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.io import atomic_write_json
from audiagentic.foundation.system.managed_service import ManagedServiceStore


@pytest.fixture
def configured(tmp_path):
    for name in ("one", "two", "replacement", "service-base"):
        (tmp_path / name).mkdir()
    for name in ("alice", "bob", "observer", "single", "node"):
        token = tmp_path / f"{name}.token"
        token.write_text(f"credential-{name}", encoding="utf-8")
        token.chmod(0o600)
    raw = {
        "schema-version": 1, "server-id": "configured-server", "listen": {"port": 8000},
        "service-root": "service-base", "node-listen": {"port": 8001},
        "projects": {"one": "one", "two": "two"},
        "principals": {
            "alice": {"token-file": "alice.token", "projects": ["one", "two"], "actions": ["submit"]},
            "bob": {"token-file": "bob.token", "projects": ["one", "two"], "actions": ["submit"]},
            "observer": {"token-file": "observer.token", "projects": ["one"], "actions": ["read"]},
            "single": {"token-file": "single.token", "projects": ["one"], "actions": ["submit"]},
        },
        "nodes": {"node": {"token-file": "node.token", "workspaces": {"workspace": "one", "other-workspace": "two"}, "principals": ["alice", "observer", "single"], "revision": 7, "enabled": True}},
    }
    path = tmp_path / "server.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    return path, raw


def authority(path):
    return NodeGrantAuthority(load_shared_server_config(path), lock_timeout=5)


def admit(owner, callback, **overrides):
    return owner.authorize_admission(**{
        "principal_id": "alice", "server_project_id": "one", "node_id": "node",
        "workspace_id": "workspace", "callback": callback, **overrides,
    })


def test_constructs_current_configured_placement_and_returns_callback_result(configured, tmp_path):
    path, _ = configured
    owner = authority(path)
    before, digest = path.read_bytes(), owner.config_digest
    result = object()
    placements = []
    mutation = tmp_path / "canonical-mutation.json"
    def commit(placement):
        placements.append(placement)
        assert type(placement) is NodeAdmissionPlacement
        atomic_write_json(mutation, placement.to_record_mapping())
        return result
    assert admit(owner, commit) is result
    selected = placements[0]
    assert selected == NodeAdmissionPlacement("configured-server", "node", "workspace", "alice", "one", 7)
    assert json.loads(mutation.read_text()) == selected.to_record_mapping()
    assert owner.service_root == ManagedServiceStore(GATEWAY_SERVICE_KEY, root=tmp_path / "service-base").root.resolve()
    assert path.read_bytes() == before and owner.config_digest == digest
    assert not (owner.service_root / "service.json").exists()
    with pytest.raises(FrozenInstanceError):
        selected.grant_revision = 99


@pytest.mark.parametrize("kwargs", [
    {"principal_id": "unknown"}, {"principal_id": "bob"}, {"principal_id": "observer"},
    {"principal_id": "single", "server_project_id": "two", "workspace_id": "other-workspace"},
    {"server_project_id": "unknown"}, {"server_project_id": "two"},
    {"node_id": "unknown"}, {"workspace_id": "unknown"},
])
def test_mismatched_or_ungranted_scopes_never_invoke_callback(configured, kwargs):
    path, _ = configured
    callback = Mock(side_effect=AssertionError("unauthorized mutation"))
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        admit(authority(path), callback, **kwargs)
    callback.assert_not_called()


@pytest.mark.parametrize("kwargs", [
    {"principal_id": "../alice"}, {"server_project_id": ""},
    {"node_id": []}, {"workspace_id": True},
])
def test_malformed_selectors_use_existing_contract_errors(configured, kwargs):
    callback = Mock()
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        admit(authority(configured[0]), callback, **kwargs)
    callback.assert_not_called()


def test_selected_workspace_and_project_can_match_second_configured_grant(configured):
    callback = Mock(return_value="committed")
    assert admit(authority(configured[0]), callback, server_project_id="two", workspace_id="other-workspace") == "committed"
    assert callback.call_args.args == (NodeAdmissionPlacement("configured-server", "node", "other-workspace", "alice", "two", 7),)


def test_disabled_grant_denied_at_startup_and_after_peer_reload(configured):
    path, _ = configured
    owner, peer = authority(path), authority(path)
    assert peer.revoke("node", expected_grant_revision=7) == 8
    callback = Mock()
    for candidate in (owner, peer, authority(path)):
        with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
            admit(candidate, callback)
    callback.assert_not_called()
    assert load_shared_server_config(path).nodes[0].revision == 8


@pytest.mark.parametrize("kwargs", [
    {"grant_revision": 99}, {"expected_grant_revision": 99},
    {"server_id": "forged-server"}, {"placement": "forged-placement"},
])
def test_caller_cannot_supply_placement_server_or_revision(configured, kwargs):
    callback = Mock()
    with pytest.raises(TypeError):
        admit(authority(configured[0]), callback, **kwargs)
    callback.assert_not_called()


def test_callback_failure_propagates_once_and_releases_the_lock(configured):
    owner = authority(configured[0])
    failure = RuntimeError("canonical mutation failed")
    callback = Mock(side_effect=failure)
    with pytest.raises(RuntimeError) as caught:
        admit(owner, callback)
    assert caught.value is failure
    callback.assert_called_once()
    assert owner.revoke("node", expected_grant_revision=7) == 8


@pytest.mark.parametrize("change", ["server", "project", "principal", "workspace", "revision", "remove-node", "comment"])
def test_unsupported_config_drift_poisoned_without_admission(configured, change):
    path, raw = configured
    owner = authority(path)
    if change == "server":
        raw["server-id"] = "changed-server"
    elif change == "project":
        raw["projects"]["one"] = "replacement"
    elif change == "principal":
        raw["principals"]["alice"]["actions"] = ["read"]
    elif change == "workspace":
        raw["nodes"]["node"]["workspaces"]["workspace"] = "two"
    elif change == "revision":
        raw["nodes"]["node"]["revision"] = 8
    elif change == "remove-node":
        del raw["nodes"]
    if change == "comment":
        path.write_bytes(path.read_bytes() + b"\n# external edit\n")
    else:
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    changed_bytes = path.read_bytes()
    callback = Mock()
    with pytest.raises(AudiaGenticError, match="Unsupported external server config edit"):
        admit(owner, callback)
    with pytest.raises(AudiaGenticError, match="uncertain"):
        admit(owner, callback)
    callback.assert_not_called()
    assert path.read_bytes() == changed_bytes


def test_uncertain_revoke_write_cannot_be_followed_by_admission(configured, monkeypatch):
    path, _ = configured
    owner = authority(path)
    original = module.atomic_write_bytes
    def fail_after_replace(target, payload):
        original(target, payload)
        if target == path:
            raise OSError("uncertain replacement")
    monkeypatch.setattr(module, "atomic_write_bytes", fail_after_replace)
    with pytest.raises(AudiaGenticError, match="uncertain"):
        owner.revoke("node", expected_grant_revision=7)
    callback = Mock()
    with pytest.raises(AudiaGenticError, match="uncertain"):
        admit(owner, callback)
    callback.assert_not_called()


def test_admission_callback_finishes_before_concurrent_revoke(configured):
    path, _ = configured
    owner, peer = authority(path), authority(path)
    entered, release, revoke_started, revoked = [threading.Event() for _ in range(4)]
    errors, placements = [], []
    def commit(placement):
        placements.append(placement)
        entered.set()
        assert release.wait(5)
    def admission():
        try:
            admit(owner, commit)
        except BaseException as exc:
            errors.append(exc)
    def revoke():
        try:
            revoke_started.set()
            peer.revoke("node", expected_grant_revision=7)
            revoked.set()
        except BaseException as exc:
            errors.append(exc)
    first, second = threading.Thread(target=admission), threading.Thread(target=revoke)
    first.start()
    try:
        assert entered.wait(5)
        second.start()
        assert revoke_started.wait(5)
        assert not revoked.wait(0.1)
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive() and not errors
    assert placements[0].grant_revision == 7 and revoked.is_set()
    denied = Mock()
    with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
        admit(owner, denied)
    denied.assert_not_called()


def test_concurrent_revoke_finishes_before_later_admission(configured, monkeypatch):
    path, _ = configured
    owner, peer = authority(path), authority(path)
    replacing, release, attempted = [threading.Event() for _ in range(3)]
    errors, denied = [], []
    callback = Mock()
    original = module.atomic_write_bytes
    def pause_replace(target, payload):
        if target == path:
            replacing.set()
            assert release.wait(5)
        original(target, payload)
    monkeypatch.setattr(module, "atomic_write_bytes", pause_replace)
    def revoke():
        try:
            peer.revoke("node", expected_grant_revision=7)
        except BaseException as exc:
            errors.append(exc)
    def admission():
        attempted.set()
        try:
            admit(owner, callback)
        except AudiaGenticError as exc:
            denied.append(exc.code)
        except BaseException as exc:
            errors.append(exc)
    first, second = threading.Thread(target=revoke), threading.Thread(target=admission)
    first.start()
    try:
        assert replacing.wait(5)
        second.start()
        assert attempted.wait(5)
        assert not callback.called
    finally:
        release.set()
        first.join(5)
        if second.ident is not None:
            second.join(5)
    assert not first.is_alive() and not second.is_alive() and not errors
    assert denied == ["CON-AGND-001"]
    callback.assert_not_called()


def _hold_admission(path, entered, release):
    owner = authority(path)
    def commit(placement):
        assert placement.grant_revision == 7
        entered.set()
        if not release.wait(10):
            raise RuntimeError("release timeout")
    admit(owner, commit)


def test_real_spawn_admission_lock_serializes_revoke(configured, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    path, _ = configured
    owner = authority(path)
    ctx = multiprocessing.get_context("spawn")
    entered, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_admission, args=(path, entered, release))
    child.start()
    try:
        assert entered.wait(10)
        owner._timeout = 0.1
        with pytest.raises(AudiaGenticError):
            owner.revoke("node", expected_grant_revision=7)
        assert load_shared_server_config(path).nodes[0].enabled
    finally:
        release.set()
        child.join(10)
        if child.is_alive():
            child.terminate()
            child.join(5)
    assert child.exitcode == 0
    owner._timeout = 5
    assert owner.revoke("node", expected_grant_revision=7) == 8
