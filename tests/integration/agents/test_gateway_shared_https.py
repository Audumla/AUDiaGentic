"""Real TLS transport qualification with a deterministic application double.

This verifies clients/ingress/leases and server files, not a native provider.
"""
from __future__ import annotations

import ipaddress
import ssl
import threading
from datetime import datetime, timedelta, timezone

import pytest

from audiagentic.components.agents.gateway.remote_client import StandaloneGatewayClient
from audiagentic.components.agents.gateway.service.application import GatewayServiceApplication
from audiagentic.components.agents.gateway.service.contract import PROTOCOL_VERSION
from audiagentic.components.agents.gateway.service.http_transport import GatewayHTTPServer
from audiagentic.components.agents.gateway.service.shared_config import (
    SharedGatewayPrincipal,
    SharedGatewayServerConfig,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.system.managed_service import ManagedServiceStore
from audiagentic.foundation.system.managed_service_contracts import ServiceKey


def _certificate(tmp_path):
    pytest.importorskip("cryptography", reason="TLS qualification needs a test certificate generator")
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "tls-cert.pem", tmp_path / "tls-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return cert_path, key_path


class FileApplication:
    def __init__(self):
        self.results = {}

    def submit_execution_request(self, root, **kwargs):
        request_id = f"req_test_{len(self.results)}"
        # Test-double execution reads the SERVER root, never the caller root.
        self.results[root, request_id] = (root / "input.txt").read_text()
        return {"request-id": request_id, "state": "completed"}

    def get_execution_response(self, root, request_id):
        return self.results[root, request_id]


def test_two_https_clients_server_files_scope_and_certificate_validation(tmp_path):
    cert, key = _certificate(tmp_path)
    roots, principals = {}, []
    for name in ("alice", "bob"):
        root = tmp_path / name
        root.mkdir()
        (root / "input.txt").write_text(f"server-file-{name}")
        token = tmp_path / f"{name}.token"
        token.write_text(f"credential-{name}")
        roots[name] = root
        principals.append(SharedGatewayPrincipal(name, token, frozenset({name}), frozenset({"read", "submit"})))
    config = SharedGatewayServerConfig(server_id="qualification", port=0, service_root=tmp_path / "service", projects=roots, principals=tuple(principals))
    store = ManagedServiceStore(ServiceKey("gateway", "tls-test"), root=config.service_root)
    record = store.create(protocol_version=PROTOCOL_VERSION, owner_epoch="tls-owner-one")
    store.transition("running", expected_revision=record.revision, expected_epoch=record.owner_epoch)
    domain = FileApplication()
    application = GatewayServiceApplication(domain, store)
    server = GatewayHTTPServer(("127.0.0.1", 0), application, "local-only", shared_config=config)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"https://127.0.0.1:{server.server_port}"
    clients = [StandaloneGatewayClient(endpoint, f"credential-{name}", shared_server_id="qualification", shared_project_id=name,
        ssl_context=ssl.create_default_context(cafile=str(cert)), request_timeout=2) for name in roots]
    try:
        for name, client in zip(roots, clients):
            admitted = client.submit_execution_request(tmp_path / "nonexistent-caller-root", execution_profile_id="test", prompt_body="read server input")
            assert client.get_execution_response(tmp_path, admitted["request-id"]) == f"server-file-{name}"
        # One principal cannot use an otherwise valid TLS connection to another project.
        wrong = StandaloneGatewayClient(endpoint, "credential-alice", shared_server_id="qualification", shared_project_id="bob",
            ssl_context=ssl.create_default_context(cafile=str(cert)), request_timeout=2)
        try:
            with pytest.raises(AudiaGenticError, match="VAL-AGSV-005"):
                wrong.list_execution_requests(tmp_path)
        finally:
            wrong.close()
        # An untrusted certificate fails before credentials or work are accepted.
        untrusted = StandaloneGatewayClient(endpoint, "credential-alice", shared_server_id="qualification", shared_project_id="alice", request_timeout=2)
        with pytest.raises(AudiaGenticError, match="NET-AGSV-002"):
            untrusted.health()
        assert len(domain.results) == 2
    finally:
        for client in clients:
            client.close()
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()
