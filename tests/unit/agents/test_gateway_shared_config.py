"""Shared config rejects ambiguous input before constructing an owner."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from audiagentic.components.agents.gateway.service import shared_config as config
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.fixture
def files(tmp_path):
    (tmp_path / "project").mkdir()
    (tmp_path / "service").mkdir()
    token = tmp_path / "token"
    token.write_text("SECRET-NOT-TO-BE-READ", encoding="utf-8")
    token.chmod(0o600)
    server = {
        "schema-version": 1, "server-id": "server-1", "listen": {"port": 8443},
        "projects": {"project_1": "project"}, "service-root": "service",
        "principals": {"alice": {"token-file": "token", "projects": ["project_1"],
                                  "actions": ["read", "submit", "cancel", "session"]}},
    }
    connector = {"schema-version": 1, "mode": "shared", "endpoint": "https://gateway.example:8443",
                 "server-id": "server-1", "token-file": "token"}
    return tmp_path, server, connector


def write(base, payload):
    path = base / "config.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_server_contract_and_relative_paths(files, monkeypatch):
    base, server, _ = files
    path = write(base, server)
    monkeypatch.chdir(base.parent)
    result = config.load_shared_server_config(path)
    assert result.server_id == "server-1"
    assert result.host == "127.0.0.1" and result.port == 8443
    assert result.service_root == (base / "service").resolve()
    assert result.projects == {"project_1": (base / "project").resolve()}
    assert result.principals == (config.SharedGatewayPrincipal(
        "alice", (base / "token").resolve(), frozenset({"project_1"}),
        frozenset({"read", "submit", "cancel", "session"})),)
    assert "SECRET" not in repr(result)
    del server["service-root"]
    server["listen"]["port"] = 0
    assert config.load_shared_server_config(write(base, server)).service_root is None


def test_connector_contract_never_reads_token(files, monkeypatch):
    base, _, connector = files
    (base / "ca.pem").write_text("certificate", encoding="utf-8")
    connector["ca-file"] = "ca.pem"
    path = write(base, connector)
    original = Path.read_text

    def guarded(self, *args, **kwargs):
        assert self.name != "token"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    result = config.load_shared_connector_config(path)
    assert result == config.SharedGatewayConnectorConfig(
        mode="shared", endpoint=connector["endpoint"], token_file=(base / "token").resolve(),
        server_id="server-1", ca_file=(base / "ca.pem").resolve())


@pytest.mark.parametrize("field,value", [
    ("schema-version", True), ("schema-version", 2), ("server-id", "../server"),
    ("server-id", "A"), ("server-id", "a" * 65), ("server-id", False),
    ("projects", {}), ("principals", {}), ("service-root", "missing"),
    ("service-root", None), ("unexpected", "SECRET"),
])
def test_server_invalid_top_level(files, field, value):
    base, server, _ = files
    server[field] = value
    with pytest.raises(AudiaGenticError) as caught:
        config.load_shared_server_config(write(base, server))
    assert caught.value.code in {"VAL-AGSV-006", "VAL-AGSV-008"}
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("port", [True, False, "443", 1.5, -1, 65536, None])
def test_port_strict_integer(files, port):
    base, server, _ = files
    server["listen"]["port"] = port
    with pytest.raises(AudiaGenticError) as caught:
        config.load_shared_server_config(write(base, server))
    assert caught.value.code == "VAL-AGSV-017"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "::1", "localhost", "127.0.0.2",
                                 "gateway.example.com", "", True])
def test_server_rejects_noncanonical_loopback_host(files, host):
    base, server, _ = files
    server["listen"]["host"] = host
    with pytest.raises(AudiaGenticError) as caught:
        config.load_shared_server_config(write(base, server))
    assert caught.value.code == "VAL-AGSV-008"


@pytest.mark.parametrize("field,value", [
    ("projects", ["unknown"]), ("projects", []), ("projects", "project_1"),
    ("actions", ["admin"]), ("actions", ["read", "read"]),
    ("token-file", "missing"), ("token-file", "project"), ("extra", True),
])
def test_principal_validation(files, field, value):
    base, server, _ = files
    server["principals"]["alice"][field] = value
    with pytest.raises(AudiaGenticError):
        config.load_shared_server_config(write(base, server))


def test_duplicate_resolved_roots(files):
    base, server, _ = files
    server["projects"]["alias"] = "project/../project"
    with pytest.raises(AudiaGenticError):
        config.load_shared_server_config(write(base, server))


@pytest.mark.parametrize("endpoint", [
    "http://example.com", "https://user:SECRET@example.com", "https://example.com/",
    "https://example.com/prefix", "https://example.com?", "https://example.com#",
    "https://example.com:bad", "https://example.com:0", "https://example.com:65536",
    "https://", "https://example.com:", "https://exa mple.com", "https://example.com\\evil",
])
def test_connector_rejects_non_origins(files, endpoint):
    base, _, connector = files
    connector["endpoint"] = endpoint
    with pytest.raises(AudiaGenticError) as caught:
        config.load_shared_connector_config(write(base, connector))
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("raw", [
    "schema-version: 1\nschema-version: 1\n",
    "schema-version: 1\nprincipals:\n  alice:\n    token-file: SECRET\n    token-file: other\n",
    "!!python/object/apply:os.system ['echo SECRET']",
    "[SECRET]", "{[SECRET]: bad}", "field: [SECRET", "",
])
def test_yaml_errors_are_safe_and_registered(files, raw):
    base, _, _ = files
    path = base / "config.yaml"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(AudiaGenticError) as caught:
        config.load_shared_server_config(path)
    assert caught.value.code == "VAL-AGSV-006"
    assert "SECRET" not in str(caught.value)
    assert caught.value.__suppress_context__ or caught.value.__context__ is None


def test_missing_config(files):
    with pytest.raises(AudiaGenticError):
        config.load_shared_connector_config(files[0] / "missing.yaml")


@pytest.mark.parametrize("raw", ["null", "true", "42", "SECRET", "[]", "- schema-version: 1"])
@pytest.mark.parametrize("loader", [config.load_shared_server_config, config.load_shared_connector_config])
def test_nonmapping_yaml(files, raw, loader):
    path = files[0] / "config.yaml"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(AudiaGenticError) as caught:
        loader(path)
    assert caught.value.code == "VAL-AGSV-006"
    assert "SECRET" not in str(caught.value)


@pytest.mark.parametrize("alias", ["token", "project/../token", "hardlink"])
def test_duplicate_principal_credential_files(files, alias):
    base, server, _ = files
    if alias == "hardlink":
        (base / alias).hardlink_to(base / "token")
    server["principals"]["bob"] = dict(server["principals"]["alice"], **{"token-file": alias})
    with pytest.raises(AudiaGenticError) as caught:
        config.load_shared_server_config(write(base, server))
    assert caught.value.code == "VAL-AGSV-011"


def test_distinct_files_are_not_compared_by_token_contents(files):
    base, server, _ = files
    other = base / "other-token"
    other.write_bytes((base / "token").read_bytes())
    other.chmod(0o600)
    server["principals"]["bob"] = dict(server["principals"]["alice"], **{"token-file": "other-token"})
    assert len(config.load_shared_server_config(write(base, server)).principals) == 2


def test_deployment_guide_yaml_examples_match_parser(tmp_path):
    guide = Path(__file__).resolve().parents[3] / "docs/guides/shared-gateway.md"
    examples = [section.split("```", 1)[0] for section in guide.read_text(
        encoding="utf-8").split("```yaml\n")[1:]]
    assert len(examples) == 4
    for directory in ("state", "projects/sample", "secrets", "trust"):
        (tmp_path / directory).mkdir(parents=True, exist_ok=True)
    for name in ("developer-a", "observer", "build-node", "local"):
        token = tmp_path / f"secrets/{name}.token"
        token.write_text(f"test-{name}", encoding="utf-8")
        token.chmod(0o600)
    (tmp_path / "trust/team-ca.pem").write_text("test fixture", encoding="utf-8")
    server = yaml.safe_load(examples[0])
    server.update(yaml.safe_load(examples[1]))
    plain = examples[3]
    examples = [examples[0], yaml.safe_dump(server), examples[2]]
    for raw, loader in zip(examples, [config.load_shared_server_config,
                                      config.load_shared_server_config,
                                      config.load_shared_connector_config], strict=True):
        path = tmp_path / "config.yaml"
        path.write_text(raw, encoding="utf-8")
        assert loader(path).server_id == "team-gateway"
    path = tmp_path / "plain.yaml"
    path.write_text(plain, encoding="utf-8")
    assert config.load_shared_connector_config(path).mode == "plain"


@pytest.mark.parametrize("field,value", [
    ("ca-file", "missing"), ("ca-file", "project"), ("token-file", "missing"),
    ("project-id", "project"), ("server-id", True), ("extra", "SECRET"), ("mode", "other"), ("mode", None),
])
def test_connector_fields(files, field, value):
    base, _, connector = files
    connector[field] = value
    with pytest.raises(AudiaGenticError):
        config.load_shared_connector_config(write(base, connector))


@pytest.mark.parametrize("section", ["listen", "principals"])
def test_unknown_nested_fields(files, section):
    base, server, _ = files
    target = server["listen"] if section == "listen" else server["principals"]["alice"]
    target["unknown"] = True
    with pytest.raises(AudiaGenticError):
        config.load_shared_server_config(write(base, server))


def test_posix_permission_policy_without_reading_token(files, monkeypatch):
    base, _, connector = files
    path = write(base, connector)
    original = Path.stat

    def insecure(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if self.name == "token":
            return SimpleNamespace(st_mode=result.st_mode | 0o040)
        return result

    monkeypatch.setattr(config, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(Path, "stat", insecure)
    with pytest.raises(AudiaGenticError) as caught:
        config.load_shared_connector_config(path)
    assert caught.value.code == "VAL-AGSV-011"


@pytest.mark.skipif(os.name != "posix", reason="Windows token ACLs are externally managed")
@pytest.mark.parametrize("mode", [0o640, 0o604, 0o660, 0o601])
def test_insecure_posix_tokens(files, mode):
    base, server, connector = files
    (base / "token").chmod(mode)
    for loader, payload in [(config.load_shared_server_config, server),
                            (config.load_shared_connector_config, connector)]:
        with pytest.raises(AudiaGenticError) as caught:
            loader(write(base, payload))
        assert caught.value.code == "VAL-AGSV-011"


def test_plain_connector_is_local_loopback_http_with_a_token_only(files):
    base, _, _ = files
    plain = {"schema-version": 1, "mode": "plain", "endpoint": "http://127.0.0.1:9000", "token-file": "token"}
    result = config.load_shared_connector_config(write(base, plain))
    assert result == config.SharedGatewayConnectorConfig(
        mode="plain", endpoint="http://127.0.0.1:9000", token_file=(base / "token").resolve())


@pytest.mark.parametrize("extra", [{"server-id": "server-1"}, {"ca-file": "token"}, {"project-id": "p"}])
def test_plain_connector_rejects_shared_fields(files, extra):
    base, _, _ = files
    plain = {"schema-version": 1, "mode": "plain", "endpoint": "http://127.0.0.1:9000", "token-file": "token", **extra}
    with pytest.raises(AudiaGenticError):
        config.load_shared_connector_config(write(base, plain))


@pytest.mark.parametrize("endpoint", [
    "https://gateway.example", "http://localhost:9000", "http://127.0.0.2:9000", "http://127.0.0.1",
    "http://127.0.0.1:0", "http://127.0.0.1:70000", "http://[::1]:9000", "http://127.0.0.1:9000/",
])
def test_plain_connector_rejects_other_origins(files, endpoint):
    base, _, _ = files
    plain = {"schema-version": 1, "mode": "plain", "endpoint": endpoint, "token-file": "token"}
    with pytest.raises(AudiaGenticError):
        config.load_shared_connector_config(write(base, plain))


def test_shared_connector_accepts_the_loopback_http_origin(files):
    base, _, connector = files
    connector["endpoint"] = "http://127.0.0.1:8765"
    assert config.load_shared_connector_config(write(base, connector)).endpoint == "http://127.0.0.1:8765"
