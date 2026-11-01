"""SH65b-3: the `a2a` settings section, the Agent Cards built from published agents, and the doctor check."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from audiagentic.components.agents.protocols.a2a.settings import (
    A2aSettings,
    load_settings,
    parse_settings,
)
from audiagentic.foundation.contracts.errors import AudiaGenticError

pb = pytest.importorskip("a2a.types.a2a_pb2", reason="needs the optional `a2a` extra")

from audiagentic.components.agents.protocols.a2a.facade import A2aRoute  # noqa: E402
from audiagentic.components.agents.protocols.a2a.publication import build_cards, published_agents  # noqa: E402

DEFINITIONS = [
    {"agent_id": "zeta", "name": "Zeta", "description": "last", "publication": {"a2a": True}},
    {"agent_id": "alpha", "name": "Alpha", "description": "first", "advertised_skills": ["review", "plan"],
     "publication": {"a2a": True}},
    {"agent_id": "hidden", "name": "Hidden", "publication": {"a2a": False, "acp": True}},
    {"agent_id": "bare"},
]


def test_defaults_are_off_and_need_nothing() -> None:
    assert parse_settings(None) == A2aSettings(False, None, None, ())
    assert parse_settings({"projects": ["one"]}).enabled is False


def test_enabling_requires_a_port_and_a_project_and_defaults_the_advertised_origin_to_loopback() -> None:
    settings = parse_settings({"enabled": True, "port": 8123, "projects": ["one", "two"]})
    assert settings.base_url == "http://127.0.0.1:8123" and settings.projects == ("one", "two")
    for bad in ({"enabled": True, "projects": ["one"]}, {"enabled": True, "port": 0, "projects": ["one"]},
                {"enabled": True, "port": True, "projects": ["one"]}, {"enabled": True, "port": 8123},
                {"enabled": True, "port": 8123, "projects": ["Bad Id"]}, {"enabled": "yes"}):
        with pytest.raises(AudiaGenticError):
            parse_settings(bad)


@pytest.mark.parametrize("url", ["https://a2a.example.invalid", "https://a2a.example.invalid:8443",
                                 "http://127.0.0.1:8123"])
def test_acceptable_advertised_origins(url: str) -> None:
    assert parse_settings({"enabled": True, "port": 8123, "projects": ["one"], "base_url": url}).base_url == url


@pytest.mark.parametrize("url", ["http://a2a.example.invalid", "http://localhost:8123", "https://a2a.example.invalid/a2a",
                                 "https://user:pw@a2a.example.invalid", "https://a2a.example.invalid/", "https://",
                                 "https://a2a.example.invalid?x=1", " https://a2a.example.invalid", "ftp://x", 7, ""])
def test_unsafe_advertised_origins_are_refused(url) -> None:
    with pytest.raises(AudiaGenticError) as raised:
        parse_settings({"enabled": True, "port": 8123, "projects": ["one"], "base_url": url})
    assert raised.value.code == "VAL-A2A-005"


def test_only_published_agents_are_served_in_a_stable_order() -> None:
    assert [d["agent_id"] for d in published_agents(DEFINITIONS)] == ["alpha", "zeta"]


def test_cards_are_per_project_and_agent_with_urls_from_the_validated_base_url_only() -> None:
    settings = parse_settings({"enabled": True, "port": 8123, "projects": ["one", "two"],
                               "base_url": "https://a2a.example.invalid"})
    cards = build_cards(settings, DEFINITIONS)
    assert sorted((r.project_id, r.agent_id) for r in cards) == [("one", "alpha"), ("one", "zeta"), ("two", "alpha"), ("two", "zeta")]
    card = cards[A2aRoute("one", "alpha")]
    interface = card.supported_interfaces[0]
    assert (interface.url, interface.protocol_binding, interface.protocol_version) == (
        "https://a2a.example.invalid/a2a/one/alpha", "JSONRPC", "1.0")
    assert [skill.id for skill in card.skills] == ["review", "plan"] and card.name == "Alpha"


def test_a_card_claims_only_what_the_facade_implements_and_declares_bearer_security() -> None:
    card = build_cards(parse_settings({"enabled": True, "port": 8123, "projects": ["one"]}), DEFINITIONS)[A2aRoute("one", "alpha")]
    assert not (card.capabilities.streaming or card.capabilities.push_notifications or card.capabilities.extended_agent_card)
    assert list(card.default_input_modes) == ["text/plain"] and list(card.default_output_modes) == ["text/plain"]
    assert card.security_schemes["bearer"].http_auth_security_scheme.scheme == "Bearer"
    assert "bearer" in card.security_requirements[0].schemes
    text = str(card)
    for private in ("execution_profile", "prompt_id", "role_ids", "/home/", "token"):
        assert private not in text


# --- the settings section through the real resolver ---------------------------------------------------------


def _explicit(tmp_path: Path, monkeypatch, body: dict) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 1, **body}), encoding="utf-8")
    monkeypatch.setenv("AUDIAGENTIC_CONFIG", str(path))


def test_the_section_loads_through_the_resolver_and_an_unknown_key_is_refused(tmp_path, monkeypatch) -> None:
    _explicit(tmp_path, monkeypatch, {"a2a": {"enabled": True, "port": 8123, "projects": ["one"]}})
    assert load_settings() == A2aSettings(True, 8123, "http://127.0.0.1:8123", ("one",))
    _explicit(tmp_path, monkeypatch, {"a2a": {"enabled": True, "port": 8123, "projects": ["one"], "bind": "0.0.0.0"}})
    with pytest.raises(AudiaGenticError):
        load_settings()  # there is no way to ask for a non-loopback bind


# --- the doctor check ---------------------------------------------------------------------------------------


def _context():
    from types import SimpleNamespace

    return SimpleNamespace(project=None)


def _ids(results) -> dict[str, str]:
    return {result.check: result.status for result in results}


def test_doctor_reports_off_invalid_and_missing_prerequisites(tmp_path, monkeypatch) -> None:
    from audiagentic.components.agents.configuration.doctor_checks import check_a2a
    from audiagentic.foundation.lifecycle.doctor import FAIL, OK

    _explicit(tmp_path, monkeypatch, {})
    assert _ids(check_a2a(_context())) == {"agents.a2a": OK}
    _explicit(tmp_path, monkeypatch, {"a2a": {"enabled": True, "port": 8123, "projects": ["one"], "base_url": "http://x.invalid"}})
    assert _ids(check_a2a(_context())) == {"agents.a2a": FAIL}
    _explicit(tmp_path, monkeypatch, {"a2a": {"enabled": True, "port": 8123, "projects": ["one"]}})
    results = _ids(check_a2a(_context()))
    assert results["agents.a2a.connector"] == FAIL  # no gateway connector configured


def _connector(tmp_path: Path, mode: str) -> Path:
    token = tmp_path / "token"
    token.write_text("not-read", encoding="utf-8")
    token.chmod(0o600)
    body = {"schema-version": 1, "mode": mode, "endpoint": "http://127.0.0.1:8443" if mode == "plain" else "https://gateway.example:8443",
            "token-file": "token", **({"server-id": "server-1"} if mode == "shared" else {})}
    path = tmp_path / "connector.yaml"
    path.write_text(yaml.safe_dump(body), encoding="utf-8")
    return path


def test_doctor_requires_a_shared_connector_not_a_plain_one(tmp_path, monkeypatch) -> None:
    from audiagentic.components.agents.configuration.doctor_checks import check_a2a
    from audiagentic.foundation.lifecycle.doctor import FAIL, OK

    base = {"a2a": {"enabled": True, "port": 8123, "projects": ["one"]}}
    _explicit(tmp_path, monkeypatch, {**base, "gateway": {"connector": str(_connector(tmp_path, "plain"))}})
    assert _ids(check_a2a(_context()))["agents.a2a.connector"] == FAIL
    _explicit(tmp_path, monkeypatch, {**base, "gateway": {"connector": str(_connector(tmp_path, "shared"))}})
    results = check_a2a(_context())
    assert _ids(results)["agents.a2a.connector"] == OK
    assert "agents.a2a.sdk" in _ids(results) and results[-1].check == "agents.a2a" and results[-1].status == OK
