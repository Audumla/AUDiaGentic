"""Opt-in transport only: real disposable loopback TLS, no native dispatch."""

from __future__ import annotations

import asyncio
import ipaddress
import ssl
import sys
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
import yaml
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed, InvalidStatus

from audiagentic.components.agents.gateway.node.authority import NodeGrantAuthority
from audiagentic.components.agents.gateway.node.connection import (
    NODE_PATH,
    SUBPROTOCOL,
    UNBOUND,
    validate_welcome,
)
from audiagentic.components.agents.gateway.node.contracts import Frame
from audiagentic.components.agents.gateway.node.transport import (
    NodeTransportClient,
    NodeTransportServer,
)
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayNodeConfig,
    load_shared_server_config,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture(scope="module")
def tls(tmp_path_factory):
    pytest.importorskip("cryptography")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    root = tmp_path_factory.mktemp("node-tls")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Disposable test CA")])
    now = datetime.now(timezone.utc)
    ca = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.KeyUsage(False, False, False, False, False, True, True, False, False),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    ca_path = root / "ca.pem"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))

    def context(name):
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        names = [x509.DNSName(name)]
        if name == "localhost":
            names.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
        leaf = (
            x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(subject)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName(names), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False
            )
            .add_extension(
                x509.KeyUsage(True, False, True, False, False, False, False, False, False),
                critical=True,
            )
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256())
        )
        certificate, private = root / f"{name}.pem", root / f"{name}.key"
        certificate.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        private.write_bytes(
            leaf_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )
        result = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        result.load_cert_chain(certificate, private)
        return result

    return SimpleNamespace(
        ca=ca_path, server=context("localhost"), wrong_host=context("other.example")
    )


@pytest_asyncio.fixture
async def channel(tmp_path, tls):
    (tmp_path / "project").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "node-state").mkdir()
    for name in ("principal", "node"):
        path = tmp_path / name
        path.write_text(f"token-{name}")
        path.chmod(0o600)
    raw = {
        "schema-version": 1,
        "server-id": "server",
        "listen": {"port": 0},
        "service-root": "state",
        "node-listen": {"port": 0},
        "projects": {"project": "project"},
        "principals": {
            "alice": {"token-file": "principal", "projects": ["project"], "actions": ["submit"]}
        },
        "nodes": {
            "node": {
                "token-file": "node",
                "workspaces": {"workspace": "project"},
                "principals": ["alice"],
                "revision": 1,
                "enabled": True,
            }
        },
    }
    path = tmp_path / "server.yaml"
    path.write_text(yaml.safe_dump(raw))
    config = load_shared_server_config(path)
    authority = NodeGrantAuthority(config, lock_timeout=2)
    server = NodeTransportServer(config, authority, gateway_owner_epoch="owner-1")
    assert server._server is None  # construction never starts a listener
    await server.start(ssl_context=tls.server)
    client = SharedGatewayNodeConfig(
        "node",
        "server",
        f"wss://127.0.0.1:{server.port}{NODE_PATH}",
        tmp_path / "node",
        tmp_path / "node-state",
        {},
        tls.ca,
    )
    try:
        yield SimpleNamespace(server=server, client=client, authority=authority, path=path, raw=raw)
    finally:
        await server.close()


def raw_connect(config, **changes):
    return connect(
        config.endpoint,
        ssl=ssl.create_default_context(cafile=str(config.ca_file)),
        proxy=None,
        subprotocols=[SUBPROTOCOL],
        additional_headers=changes.pop(
            "additional_headers", {"Authorization": "Bearer token-node"}
        ),
        **changes,
    )


def hello(**changes):
    values = dict(
        version=1,
        type="hello",
        message_id="hello-1",
        node_id="node",
        node_epoch="boot-1",
        gateway_owner_epoch=UNBOUND,
        sequence=1,
        payload={
            "protocol-version": 1,
            "server-id": "server",
            "challenge": "challenge-1",
            "reconnect-checkpoint": 0,
        },
    )
    return Frame(**(values | changes))


async def raw_handshake(config):
    websocket = await raw_connect(config)
    await websocket.send(hello().to_bytes())
    welcome = Frame.from_bytes(await asyncio.wait_for(websocket.recv(), 2))
    return websocket, welcome


async def wait_until(predicate):
    async def wait():
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(wait(), 3)


@pytest.mark.asyncio
async def test_real_tls_authenticated_handshake_and_generation_replacement(channel):
    first = await NodeTransportClient(channel.client, node_epoch="boot-1").connect()
    try:
        assert first.identity.gateway_owner_epoch == "owner-1"
        assert first.identity.connection_generation == 1
        assert first.grant_revision == 1
        old = channel.authority.serialize(lambda: channel.server.owner._active["node"])
        second = await NodeTransportClient(channel.client, node_epoch="boot-1").connect()
        try:
            await asyncio.wait_for(first.wait_closed(), 2)
            assert second.identity.connection_generation == 2
            assert not await asyncio.to_thread(channel.server.owner.remove, old)
            assert (
                channel.authority.serialize(lambda: channel.server.owner.current_identity("node"))
                == second.identity
            )
            await second.heartbeat()
        finally:
            await second.close()
    finally:
        await first.close()
    await wait_until(lambda: not channel.server.owner._active)
    third = await NodeTransportClient(channel.client, node_epoch="boot-2").connect()
    try:
        assert third.identity.connection_generation == 3
        assert third.identity.node_epoch == "boot-2"
    finally:
        await third.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,status",
    [
        ("missing", 401),
        ("wrong", 401),
        ("principal", 401),
        ("duplicate", 401),
        ("path", 404),
        ("query", 404),
        ("origin", 403),
        ("duplicate-origin", 403),
    ],
)
async def test_real_tls_upgrade_rejects_before_authoritative_hello(channel, case, status):
    config = channel.client
    headers = [("Authorization", "Bearer token-node")]
    kwargs = {}
    if case == "missing":
        headers = []
    elif case == "wrong":
        headers = [("Authorization", "Bearer wrong")]
    elif case == "principal":
        headers = [("Authorization", "Bearer token-principal")]
    elif case == "duplicate":
        headers *= 2
    elif case == "path":
        config = replace(config, endpoint=config.endpoint.replace(NODE_PATH, "/other"))
    elif case == "query":
        config = replace(config, endpoint=config.endpoint + "?extra=1")
    elif case == "origin":
        kwargs["origin"] = "https://browser.example"
    else:
        headers += [("Origin", "https://browser.example"), ("Origin", "https://browser.example")]
    with pytest.raises(InvalidStatus) as error:
        async with raw_connect(config, additional_headers=headers, **kwargs):
            pytest.fail("Unauthorized upgrade succeeded")
    assert error.value.response.status_code == status
    assert not channel.server.owner._active


@pytest.mark.asyncio
async def test_revocation_prevents_new_authenticated_connection(channel):
    channel.authority.revoke("node", expected_grant_revision=1)
    with pytest.raises(InvalidStatus) as error:
        await NodeTransportClient(channel.client, node_epoch="boot-1").connect()
    assert error.value.response.status_code == 401
    assert not channel.server.owner._active


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "node",
        "epoch",
        "sentinel",
        "sequence",
        "server",
        "boolean-version",
        "extra",
        "checkpoint",
        "text",
    ],
)
async def test_authenticated_hello_is_strict_before_generation_publication(channel, mutation):
    frame = hello()
    if mutation == "node":
        frame = replace(frame, node_id="other")
    elif mutation == "epoch":
        frame = replace(frame, node_epoch=UNBOUND)
    elif mutation == "sentinel":
        frame = replace(frame, gateway_owner_epoch="owner-1")
    elif mutation == "sequence":
        frame = replace(frame, sequence=2)
    elif mutation == "server":
        frame = replace(frame, payload=dict(frame.payload) | {"server-id": "other"})
    elif mutation == "boolean-version":
        frame = replace(frame, payload=dict(frame.payload) | {"protocol-version": True})
    elif mutation == "extra":
        frame = replace(frame, payload=dict(frame.payload) | {"connection-generation": 123})
    elif mutation == "checkpoint":
        frame = replace(frame, payload=dict(frame.payload) | {"reconnect-checkpoint": 1})
    async with raw_connect(channel.client) as websocket:
        await websocket.send(frame.to_bytes().decode() if mutation == "text" else frame.to_bytes())
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(websocket.recv(), 2)
    assert not channel.server.owner._active


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "hello",
        "welcome",
        "command",
        "receipt",
        "effect-authorize",
        "reconcile",
        "revoke",
        "epoch",
        "generation",
        "sequence",
        "extra",
        "bool-generation",
        "text",
        "oversized",
    ],
)
async def test_post_welcome_rejects_wrong_state_direction_and_disabled_work(channel, mutation):
    websocket, welcome = await raw_handshake(channel.client)
    try:
        frame = Frame(
            1,
            "heartbeat",
            "heartbeat-2",
            "node",
            "boot-1",
            "owner-1",
            2,
            {"connection-generation": welcome.payload["connection-generation"]},
        )
        if mutation in {
            "hello",
            "welcome",
            "command",
            "receipt",
            "effect-authorize",
            "reconcile",
            "revoke",
        }:
            frame = replace(frame, type=mutation)
        elif mutation == "epoch":
            frame = replace(frame, gateway_owner_epoch=UNBOUND)
        elif mutation == "generation":
            frame = replace(frame, payload={"connection-generation": 999})
        elif mutation == "sequence":
            frame = replace(frame, sequence=1)
        elif mutation == "extra":
            frame = replace(frame, payload=dict(frame.payload) | {"progress": "working"})
        elif mutation == "bool-generation":
            frame = replace(frame, payload={"connection-generation": True})
        data = frame.to_bytes()
        if mutation == "text":
            data = data.decode()
        elif mutation == "oversized":
            data = b"x" * (1024 * 1024 + 1)
        await websocket.send(data)
        with pytest.raises(ConnectionClosed):
            await asyncio.wait_for(websocket.recv(), 2)
    finally:
        await websocket.close()


@pytest.mark.asyncio
async def test_heartbeat_only_updates_transport_liveness_no_execution_sinks(channel, monkeypatch):
    from audiagentic.components.agents.gateway import store

    def forbidden(*args, **kwargs):
        pytest.fail("Transport heartbeat invoked canonical work mutation")

    for name in (
        "authorize_owned_node_effect",
        "apply_owned_node_receipt",
        "bind_owned_node_dispatch",
        "update_diagnostics",
    ):
        monkeypatch.setattr(store, name, forbidden)
    client = await NodeTransportClient(channel.client, node_epoch="boot-1").connect()
    try:
        # Receipt may occur within the same monotonic clock tick on Windows.
        # Prove processing and timestamp assignment without requiring tick advance.
        client.last_liveness_at = 0
        slot = channel.authority.serialize(lambda: channel.server.owner._active["node"])
        frame = Frame(
            1,
            "heartbeat",
            "heartbeat-2",
            "node",
            "boot-1",
            "owner-1",
            2,
            {"connection-generation": client.identity.connection_generation},
        )
        await slot.websocket.send(frame.to_bytes())
        await wait_until(lambda: client._received_sequence == 2 and client.last_liveness_at > 0)
        await client.heartbeat()
        assert client.events.empty()
        assert client.grant_revision == 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_direct_client_disables_environment_proxy(channel, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("WSS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    connection = await NodeTransportClient(channel.client, node_epoch="boot-1").connect()
    await connection.close()


@pytest.mark.asyncio
async def test_real_tls_redirect_never_forwards_credentials(channel, tls):
    requests = []

    async def target_request(connection, request):
        requests.append("target")

    async with serve(
        lambda ws: ws.wait_closed(), "127.0.0.1", 0, ssl=tls.server, process_request=target_request
    ) as target:
        destination = f"wss://127.0.0.1:{target.sockets[0].getsockname()[1]}{NODE_PATH}"

        async def redirect(connection, request):
            requests.append("redirect")
            response = connection.respond(307, "redirect\n")
            response.headers["Location"] = destination
            return response

        async with serve(
            lambda ws: ws.wait_closed(), "127.0.0.1", 0, ssl=tls.server, process_request=redirect
        ) as source:
            config = replace(
                channel.client,
                endpoint=f"wss://127.0.0.1:{source.sockets[0].getsockname()[1]}{NODE_PATH}",
            )
            with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
                await NodeTransportClient(config, node_epoch="boot-1").connect()
    assert requests == ["redirect"]


@pytest.mark.asyncio
async def test_tls_certificate_verification_required(channel, tls):
    with pytest.raises(ssl.SSLCertVerificationError):
        await NodeTransportClient(
            replace(channel.client, ca_file=None), node_epoch="boot-1"
        ).connect()
    async with serve(lambda ws: ws.wait_closed(), "127.0.0.1", 0, ssl=tls.wrong_host) as wrong:
        config = replace(
            channel.client,
            endpoint=f"wss://127.0.0.1:{wrong.sockets[0].getsockname()[1]}{NODE_PATH}",
        )
        with pytest.raises(ssl.SSLCertVerificationError):
            await NodeTransportClient(config, node_epoch="boot-1").connect()


@pytest.mark.parametrize(
    "endpoint",
    [
        "ws://127.0.0.1/shared/v1/nodes/connect",
        "wss://user:secret@example/shared/v1/nodes/connect",
        "wss://example/other",
        "wss://example/shared/v1/nodes/connect?x=1",
        "wss://example/shared/v1/nodes/connect#",
        "wss://example:0/shared/v1/nodes/connect",
        "wss://example:/shared/v1/nodes/connect",
        "wss://example/shared\\v1/nodes/connect",
    ],
)
def test_client_validates_exact_supported_wss_endpoint(endpoint, tmp_path):
    config = SharedGatewayNodeConfig("node", "server", endpoint, tmp_path / "token", tmp_path, {})
    with pytest.raises(AudiaGenticError, match="VAL-AGND-001"):
        NodeTransportClient(config, node_epoch="boot-1")


@pytest.mark.parametrize(
    "mutation", ["challenge", "server", "epoch", "generation", "revision", "extra", "not-reconcile"]
)
def test_welcome_schema_and_challenge_are_strict(mutation):
    frame = Frame(
        1,
        "welcome",
        "welcome-1",
        "node",
        "boot-1",
        "owner-1",
        1,
        {
            "protocol-version": 1,
            "server-id": "server",
            "challenge": "challenge-1",
            "connection-generation": 1,
            "grant-revision": 1,
            "reconcile-required": True,
        },
    )
    changes = {
        "challenge": {"challenge": "other"},
        "server": {"server-id": "other"},
        "generation": {"connection-generation": True},
        "revision": {"grant-revision": 0},
        "extra": {"authorization-id": "forged"},
        "not-reconcile": {"reconcile-required": False},
    }
    frame = (
        replace(frame, gateway_owner_epoch=UNBOUND)
        if mutation == "epoch"
        else replace(frame, payload=dict(frame.payload) | changes[mutation])
    )
    with pytest.raises(AudiaGenticError):
        validate_welcome(
            frame, node_id="node", node_epoch="boot-1", server_id="server", challenge="challenge-1"
        )


@pytest.mark.asyncio
async def test_bounded_control_inbox_closes_instead_of_dropping(channel):
    client = await NodeTransportClient(channel.client, node_epoch="boot-1").connect()
    try:
        slot = channel.authority.serialize(lambda: channel.server.owner._active["node"])
        for sequence in range(2, 11):
            frame = Frame(
                1,
                "error",
                f"error-{sequence}",
                "node",
                "boot-1",
                "owner-1",
                sequence,
                {
                    "connection-generation": client.identity.connection_generation,
                    "code": "CON-AGND-001",
                },
            )
            await slot.websocket.send(frame.to_bytes())
        await asyncio.wait_for(client.wait_closed(), 2)
        assert client.events.qsize() == client.events.maxsize == 8
        assert client.failure == "CON-AGND-001"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_gateway_revoke_control_is_delivered_without_executing_or_resuming_work(channel):
    client = await NodeTransportClient(channel.client, node_epoch="boot-1").connect()
    try:
        slot = channel.authority.serialize(lambda: channel.server.owner._active["node"])
        frame = Frame(
            1,
            "revoke",
            "revoke-2",
            "node",
            "boot-1",
            "owner-1",
            2,
            {"connection-generation": client.identity.connection_generation, "grant-revision": 2},
        )
        before = client.last_liveness_at
        await slot.websocket.send(frame.to_bytes())
        event = await asyncio.wait_for(client.events.get(), 2)
        assert event.type == "revoke" and event.grant_revision == 2
        await asyncio.wait_for(client.wait_closed(), 2)
        assert client.last_liveness_at == before
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["server", "challenge", "epoch"])
async def test_real_tls_client_rejects_mismatched_welcome(channel, tls, mutation):
    async def wrong_welcome(websocket):
        request = Frame.from_bytes(await websocket.recv())
        frame = Frame(
            1,
            "welcome",
            "welcome-1",
            "node",
            "boot-1",
            "owner-1",
            1,
            {
                "protocol-version": 1,
                "server-id": "server",
                "challenge": request.payload["challenge"],
                "connection-generation": 1,
                "grant-revision": 1,
                "reconcile-required": True,
            },
        )
        if mutation == "epoch":
            frame = replace(frame, gateway_owner_epoch=UNBOUND)
        else:
            key = "server-id" if mutation == "server" else "challenge"
            frame = replace(frame, payload=dict(frame.payload) | {key: "wrong"})
        await websocket.send(frame.to_bytes())
        await websocket.wait_closed()

    async with serve(
        wrong_welcome, "127.0.0.1", 0, ssl=tls.server, subprotocols=[SUBPROTOCOL]
    ) as server:
        config = replace(
            channel.client,
            endpoint=f"wss://127.0.0.1:{server.sockets[0].getsockname()[1]}{NODE_PATH}",
        )
        with pytest.raises(AudiaGenticError, match="CON-AGND-001"):
            await NodeTransportClient(config, node_epoch="boot-1").connect()


def test_python310_grammar_and_node_extra_are_explicit():
    import ast
    from pathlib import Path

    root = Path(__file__).parents[3]
    for name in ("transport", "connection"):
        source = (root / f"src/audiagentic/components/agents/gateway/node/{name}.py").read_text()
        ast.parse(source, feature_version=(3, 10))
        assert "asyncio.timeout" not in source
    from packaging.requirements import Requirement

    if sys.version_info >= (3, 11):
        from audiagentic.foundation.toolchains.config.config_reader import load_config

        metadata = load_config(root / "pyproject.toml")
    else:
        # pytest supplies tomli on Python 3.10; Foundation's current reader
        # imports stdlib tomllib, so don't import it on that interpreter.
        import tomli

        metadata = tomli.loads((root / "pyproject.toml").read_text())
    requirements = [
        Requirement(value) for value in metadata["project"]["optional-dependencies"]["node"]
    ]
    requirement = next(value for value in requirements if value.name == "websockets")
    assert "15.0" in requirement.specifier and "15.0.1" in requirement.specifier
    assert "14.2" not in requirement.specifier and "16.0" not in requirement.specifier


@pytest.mark.asyncio
async def test_cancellation_during_threaded_publication_closes_replaced_idle_socket(
    channel, monkeypatch
):
    first = await NodeTransportClient(channel.client, node_epoch="boot-1").connect()
    original = channel.server.owner.replace
    entered, release = threading.Event(), threading.Event()
    captured = {}

    def blocked_replace(node_id, node_epoch, websocket):
        captured["websocket"] = websocket
        entered.set()
        if not release.wait(5):
            raise AssertionError("Test did not release connection publication")
        return original(node_id, node_epoch, websocket)

    monkeypatch.setattr(channel.server.owner, "replace", blocked_replace)
    second = await raw_connect(channel.client)
    try:
        await second.send(hello().to_bytes())
        await wait_until(entered.is_set)
        # websockets 15's handler registry exposes the actual TLS handler task.
        handler = channel.server._server.handlers[captured["websocket"]]
        handler.cancel()
        await asyncio.sleep(0)  # deliver cancellation while publication is blocked
        assert not handler.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(handler, return_exceptions=True), 3)
        await asyncio.wait_for(first.wait_closed(), 2)
        await asyncio.wait_for(second.wait_closed(), 2)
        assert not channel.server.owner._active
        assert channel.server.owner._generations["node"] == 2
    finally:
        release.set()
        await second.close()
        await first.close()


@pytest.mark.asyncio
async def test_welcome_send_failure_closes_both_connections_and_removes_exact_slot(
    channel, monkeypatch
):
    first = await NodeTransportClient(channel.client, node_epoch="boot-1").connect()
    original = channel.server.owner.replace

    def fail_welcome(node_id, node_epoch, websocket):
        result = original(node_id, node_epoch, websocket)

        async def fail_send(_message):
            raise ConnectionError("simulated welcome send failure")

        websocket.send = fail_send
        return result

    monkeypatch.setattr(channel.server.owner, "replace", fail_welcome)
    try:
        with pytest.raises(ConnectionClosed):
            await NodeTransportClient(channel.client, node_epoch="boot-1").connect()
        await asyncio.wait_for(first.wait_closed(), 2)
        await wait_until(lambda: not channel.server.owner._active)
        assert channel.server.owner._generations["node"] == 2
    finally:
        await first.close()


@pytest.mark.asyncio
async def test_close_timeout_aborts_wedged_socket(monkeypatch):
    from audiagentic.components.agents.gateway.node import connection as module

    aborted = []

    async def never_close(**kwargs):
        await asyncio.Event().wait()

    websocket = SimpleNamespace(
        close=never_close, transport=SimpleNamespace(abort=lambda: aborted.append(True))
    )
    monkeypatch.setattr(module, "CLOSE_TIMEOUT_SECONDS", 0.01)
    await asyncio.wait_for(module.close_socket(websocket), 1)
    assert aborted == [True]
