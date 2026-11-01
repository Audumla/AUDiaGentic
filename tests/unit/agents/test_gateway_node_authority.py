"""Ordering and durable config CAS for central node grants."""
import multiprocessing
import threading
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from audiagentic.components.agents.gateway.node import authority as module
from audiagentic.components.agents.gateway.node.authority import (
    NodeConnectionIdentity,
    NodeGrantAuthority,
    SealedNodePlacement,
)
from audiagentic.components.agents.gateway.node.contracts import CommandIdentity
from audiagentic.components.agents.gateway.service.shared_config import load_shared_server_config
from audiagentic.foundation.contracts.errors import AudiaGenticError
from tests.helpers.shared_gateway import declare_project


@pytest.fixture
def setup(tmp_path):
    declare_project(tmp_path / "project", "project")
    for name in ("principal", "node"):
        path = tmp_path / name
        path.write_text(f"token-{name}", encoding="utf-8")
        path.chmod(0o600)
    raw = {
        "schema-version": 1, "server-id": "server", "listen": {"port": 8000},
        "node-listen": {"port": 8001}, "projects": ["project"],
        "principals": {"alice": {"token-file": "principal", "projects": ["project"], "actions": ["submit"]}},
        "nodes": {"node": {"token-file": "node", "workspaces": {"workspace": "project"},
                           "principals": ["alice"], "revision": 1, "enabled": True}},
    }
    path = tmp_path / "server.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    identity = CommandIdentity("command", "request", "node", "epoch", "owner", 1,
                               "workspace", 1, 1, "a" * 64, "profile")
    placement = SealedNodePlacement(identity, "server", "alice", "project")
    live = NodeConnectionIdentity("node", "epoch", "owner", 1)
    return path, placement, live


def authority(path):
    return NodeGrantAuthority(load_shared_server_config(path), lock_timeout=5)


def authorize(owner, placement, live, callback=lambda: "mutated"):
    return owner.authorize_effect(placement, connection=lambda: live, callback=callback)


def test_revoke_restart_and_peer_reload(setup):
    path, placement, live = setup
    owner, peer = authority(path), authority(path)
    digest = owner.config_digest
    assert authorize(owner, placement, live) == "mutated"
    assert owner.revoke("node", expected_grant_revision=1, expected_config_digest=digest) == 2
    assert owner.config_digest != digest
    for instance in (owner, peer, authority(path)):
        with pytest.raises(AudiaGenticError):
            authorize(instance, placement, live)
    config = load_shared_server_config(path)
    assert config.nodes[0].revision == 2 and config.nodes[0].enabled is False


@pytest.mark.parametrize("field,value", [("server_id", "other"), ("principal_id", "other"),
                                        ("server_project_id", "other")])
def test_wrong_placement_scopes(setup, field, value):
    path, placement, live = setup
    with pytest.raises(AudiaGenticError):
        authorize(authority(path), replace(placement, **{field: value}), live,
                  lambda: pytest.fail("unauthorized callback"))


@pytest.mark.parametrize("field,value", [("node_id", "other"), ("workspace_id", "other"),
                                        ("grant_revision", 2), ("node_epoch", "old"),
                                        ("gateway_owner_epoch", "old"), ("connection_generation", 2)])
def test_stale_identity(setup, field, value):
    path, placement, live = setup
    placement = replace(placement, identity=replace(placement.identity, **{field: value}))
    with pytest.raises(AudiaGenticError):
        authorize(authority(path), placement, live, lambda: pytest.fail("unauthorized callback"))


def test_stale_digest_and_revision_never_write(setup):
    path, _, _ = setup
    owner = authority(path)
    before = path.read_bytes()
    for revision, digest in [(True, None), (2, None), (1, "0" * 64)]:
        with pytest.raises(AudiaGenticError):
            owner.revoke("node", expected_grant_revision=revision, expected_config_digest=digest)
        assert path.read_bytes() == before


@pytest.mark.parametrize("change", ["comment", "project", "revision", "remove"])
def test_unsupported_external_edits_fail_closed(setup, change):
    path, placement, live = setup
    owner = authority(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if change == "comment":
        path.write_bytes(path.read_bytes() + b"\n# external edit\n")
    else:
        if change == "project":
            raw["nodes"]["node"]["workspaces"] = {"other": "project"}
        elif change == "revision":
            raw["nodes"]["node"]["revision"] = 2
        else:
            del raw["nodes"]
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(AudiaGenticError):
        authorize(owner, placement, live)
    with pytest.raises(AudiaGenticError):
        owner.revoke("node", expected_grant_revision=1)


@pytest.mark.parametrize("after_replace", [False, True])
def test_uncertain_write_never_restores_or_reauthorizes(setup, monkeypatch, after_replace):
    path, placement, live = setup
    owner = authority(path)
    before = path.read_bytes()
    original = module.atomic_write_bytes

    def uncertain(target, payload):
        if target == path:
            if after_replace:
                original(target, payload)
            raise OSError("secret must not escape")
        original(target, payload)

    monkeypatch.setattr(module, "atomic_write_bytes", uncertain)
    with pytest.raises(AudiaGenticError, match="uncertain") as caught:
        owner.revoke("node", expected_grant_revision=1)
    assert "secret" not in str(caught.value)
    assert (path.read_bytes() != before) is after_replace
    with pytest.raises(AudiaGenticError):
        authorize(owner, placement, live)
    if after_replace:
        with pytest.raises(AudiaGenticError):
            authorize(authority(path), placement, live)


def test_effect_callback_exception_not_retried(setup):
    path, placement, live = setup
    calls = []

    def callback():
        calls.append(1)
        raise RuntimeError("mutation failed")

    with pytest.raises(RuntimeError):
        authorize(authority(path), placement, live, callback)
    assert calls == [1]


def test_revoke_waits_for_effect_mutator(setup):
    path, placement, live = setup
    owner, peer = authority(path), authority(path)
    entered, release, revoke_started, revoked = [threading.Event() for _ in range(4)]
    errors = []

    def mutate():
        entered.set()
        assert release.wait(5)

    def effect():
        try:
            authorize(owner, placement, live, mutate)
        except BaseException as exc:
            errors.append(exc)

    def revoke():
        try:
            revoke_started.set()
            peer.revoke("node", expected_grant_revision=1)
            revoked.set()
        except BaseException as exc:
            errors.append(exc)

    first = threading.Thread(target=effect)
    second = threading.Thread(target=revoke)
    first.start()
    assert entered.wait(5)
    second.start()
    assert revoke_started.wait(5)
    assert not revoked.wait(0.15)
    release.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive() and not errors
    assert revoked.is_set()
    with pytest.raises(AudiaGenticError):
        authorize(owner, placement, live)


def _hold_authorization(path, placement, live, entered, release):
    owner = authority(path)

    def callback():
        entered.set()
        if not release.wait(10):
            raise RuntimeError("test release timeout")

    authorize(owner, placement, live, callback)


def test_real_spawn_process_lock_orders_revoke(setup, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    path, placement, live = setup
    owner = authority(path)
    ctx = multiprocessing.get_context("spawn")
    entered, release = ctx.Event(), ctx.Event()
    child = ctx.Process(target=_hold_authorization, args=(path, placement, live, entered, release))
    child.start()
    try:
        assert entered.wait(10)
        # Use an already initialized authority; startup also uses the same lock.
        contender = owner
        contender._timeout = 0.15
        with pytest.raises(AudiaGenticError):
            contender.revoke("node", expected_grant_revision=1)
        assert load_shared_server_config(path).nodes[0].enabled
    finally:
        release.set()
        child.join(10)
        if child.is_alive():
            child.terminate()
            child.join(5)
    assert child.exitcode == 0
    owner._timeout = 5
    assert owner.revoke("node", expected_grant_revision=1) == 2


def test_connection_replacement_is_serialized_and_stale_channel_denied(setup):
    path, placement, live = setup
    owner = authority(path)
    current = [live]
    owner.serialize(lambda: current.__setitem__(0, replace(live, connection_generation=2)))
    with pytest.raises(AudiaGenticError):
        owner.authorize_effect(placement, connection=lambda: current[0],
                               callback=lambda: pytest.fail("stale connection"))


def test_complete_candidate_validated_before_config_replace(setup, monkeypatch):
    path, _, _ = setup
    owner = authority(path)
    before = path.read_bytes()
    original = module.load_shared_server_config

    def reject_candidate(target):
        if target != path:
            raise ValueError("candidate validation failed")
        return original(target)

    monkeypatch.setattr(module, "load_shared_server_config", reject_candidate)
    with pytest.raises(ValueError):
        owner.revoke("node", expected_grant_revision=1)
    assert path.read_bytes() == before
    assert not list(path.parent.glob(".node-grant-*.yaml"))


def test_startup_rejects_missing_config_reference_and_stale_config(setup):
    path, _, _ = setup
    config = load_shared_server_config(path)
    with pytest.raises(AudiaGenticError):
        NodeGrantAuthority(replace(config, config_path=None))
    authority(path).revoke("node", expected_grant_revision=1)
    with pytest.raises(AudiaGenticError):
        NodeGrantAuthority(config)


def test_authorization_digest_cas_and_invalidated_external_edit(setup):
    path, placement, live = setup
    owner = authority(path)
    before = path.read_bytes()
    with pytest.raises(AudiaGenticError):
        owner.authorize_effect(placement, connection=lambda: live,
                               callback=lambda: pytest.fail("stale digest"),
                               expected_config_digest="0" * 64)
    path.write_bytes(before + b"\n# unsupported edit\n")
    with pytest.raises(AudiaGenticError):
        authorize(owner, placement, live)
    path.write_bytes(before)
    with pytest.raises(AudiaGenticError):
        authorize(owner, placement, live)


@pytest.mark.parametrize("other_identity", ["principal", "node"])
def test_startup_rejects_equal_tokens_in_distinct_files(setup, other_identity):
    path, _, _ = setup
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    duplicate = path.parent / "duplicate.token"
    duplicate.write_bytes((path.parent / other_identity).read_bytes())
    duplicate.chmod(0o600)
    raw["nodes"]["other"] = dict(raw["nodes"]["node"], **{"token-file": "duplicate.token"})
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(AudiaGenticError, match="distinct auth tokens") as caught:
        authority(path)
    assert "token-principal" not in str(caught.value)
    assert "token-node" not in str(caught.value)


def test_constructor_accepts_service_root_without_splitting_config_lock(setup):
    path, _, _ = setup
    config = load_shared_server_config(path)
    owner = NodeGrantAuthority(config)
    peer = NodeGrantAuthority(config, service_root=owner.service_root)
    assert owner.lock_path == peer.lock_path
    with pytest.raises(AudiaGenticError, match="service root"):
        NodeGrantAuthority(config, path.parent / "wrong-service")


def test_config_cannot_collide_with_managed_service_state(setup):
    path, _, _ = setup
    config = load_shared_server_config(path)
    owner = NodeGrantAuthority(config)
    # Supply a config whose service-root resolves its managed root to the
    # config directory; no managed-service files need to be written for this check.
    from unittest.mock import patch

    with patch.object(module, "ManagedServiceStore") as store:
        store.return_value.root = path.parent
        with pytest.raises(AudiaGenticError, match="outside managed service state"):
            NodeGrantAuthority(config, service_root=path.parent)
    assert owner.path == path.resolve()


def test_lost_ack_revoke_retry_is_idempotent_after_restart(setup, monkeypatch):
    path, _, _ = setup
    owner = authority(path)
    peer = authority(path)
    assert owner.revoke("node", expected_grant_revision=1) == 2
    before = path.read_bytes()

    def no_write(*args, **kwargs):
        pytest.fail("idempotent revoke must not write")

    monkeypatch.setattr(module, "atomic_write_bytes", no_write)
    for current in (owner, peer, authority(path)):
        assert current.revoke("node", expected_grant_revision=1) == 2
    assert path.read_bytes() == before
    for revision in (0, 2, 3, True):
        with pytest.raises(AudiaGenticError):
            owner.revoke("node", expected_grant_revision=revision)


def test_revoke_has_single_canonical_revision_keyword(setup):
    path, _, _ = setup
    with pytest.raises(TypeError):
        authority(path).revoke("node", expected_revision=1)


def test_read_only_principal_cannot_authorize_submission_effect(setup):
    path, placement, live = setup
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["principals"]["alice"]["actions"] = ["read"]
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(AudiaGenticError):
        authorize(authority(path), placement, live,
                  lambda: pytest.fail("read-only principal reached effect mutator"))
    with pytest.raises(TypeError):
        SealedNodePlacement(placement.identity, "server", "alice", "project", action="read")
