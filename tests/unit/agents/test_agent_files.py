"""CFG05: agent files, templates and their compilation to catalog records."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.components.agents.configuration.agent_files import compile_catalog, resolve_agents
from audiagentic.components.agents.configuration.contracts import AgentsConfigDocument
from audiagentic.components.agents.models.agent_definition import agent_definition_from_dict
from audiagentic.components.agents.models.execution_profile import execution_profile_from_dict
from audiagentic.components.agents.models.role import role_from_dict
from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.launcher import _main


@pytest.fixture
def scopes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    monkeypatch.chdir(root)
    return {"user": tmp_path / "xdg" / "audiagentic", "project": root / ".audiagentic", "root": root}


def _write(base: Path, kind: str, name: str, text: str) -> Path:
    path = base / kind / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_minimal_agent_extends_packaged_template(scopes: dict[str, Path]) -> None:
    _write(scopes["user"], "agents", "reviewer-gpt-agent",
           "schema_version: 1\nextends: reviewer\nprovider: gpt-auto\nmodel: chatgpt\n")
    agent = resolve_agents()["reviewer-gpt-agent"]
    assert agent.template == "reviewer"
    assert agent.fields["provider"] == "gpt-auto"
    assert agent.fields["surface"] == "gpt-auto-cdp"  # the provider's only surface
    assert "Review the plan item" in agent.fields["instructions"]
    assert agent.origins["/instructions"].scope == "vendor"
    assert agent.origins["/model"].scope == "user"


def test_project_scope_overrides_user_and_template(scopes: dict[str, Path]) -> None:
    _write(scopes["user"], "agents", "r", "schema_version: 1\nextends: reviewer\nprovider: gpt-auto\nmodel: chatgpt\n")
    _write(scopes["project"], "agents", "r", "schema_version: 1\nname: Team reviewer\nskills: [review, planning]\n")
    _write(scopes["project"], "templates", "reviewer", "schema_version: 1\ninstructions: Team review rules.\n")
    agent = resolve_agents()["r"]
    assert agent.fields["name"] == "Team reviewer"
    assert agent.fields["skills"] == ["review", "planning"]
    assert agent.fields["instructions"] == "Team review rules."
    assert agent.origins["/instructions"].scope == "project"
    assert agent.fields["description"].startswith("Reviews plans")  # still inherited from the vendor template


def test_null_removes_an_inherited_field(scopes: dict[str, Path]) -> None:
    _write(scopes["user"], "agents", "r",
           "schema_version: 1\nextends: reviewer\nprovider: gpt-auto\nmodel: chatgpt\nskills: null\n")
    agent = resolve_agents()["r"]
    assert "skills" not in agent.fields
    assert agent.origins["/skills"].deleted


def test_surface_rules(scopes: dict[str, Path]) -> None:
    _write(scopes["user"], "agents", "none", "schema_version: 1\nprovider: claude\nmodel: m\ninstructions: x\n")
    _write(scopes["user"], "agents", "picked",
           "schema_version: 1\nprovider: opencode\nmodel: m\ninstructions: x\nsurface: opencode-acp\n")
    agents = resolve_agents()
    assert "surface" not in agents["none"].fields
    assert agents["picked"].fields["surface"] == "opencode-acp"
    _write(scopes["user"], "agents", "ambiguous", "schema_version: 1\nprovider: opencode\nmodel: m\ninstructions: x\n")
    with pytest.raises(AudiaGenticError) as raised:
        resolve_agents()
    assert raised.value.code == "CFG-AGF-004"


@pytest.mark.parametrize(
    ("kind", "text", "code"),
    [
        ("agents", "schema_version: 1\nprovider: gpt-auto\nmodle: x\n", "CFG-AGF-001"),
        ("agents", "schema_version: 1\nextends: nope\nprovider: gpt-auto\nmodel: m\n", "CFG-AGF-002"),
        ("templates", "schema_version: 1\nextends: reviewer\n", "CFG-AGF-002"),
        ("agents", "schema_version: 1\nprovider: gpt-auto\n", "CFG-AGF-003"),
        ("agents", "schema_version: 1\nid: other\nprovider: gpt-auto\nmodel: m\ninstructions: x\n", "CFG-AGF-006"),
        ("agents", "provider: gpt-auto\nmodel: m\ninstructions: x\n", "CFG-AGF-001"),
    ],
)
def test_invalid_files_fail_with_their_code(scopes: dict[str, Path], kind: str, text: str, code: str) -> None:
    _write(scopes["user"], kind, "bad", text)
    with pytest.raises(AudiaGenticError) as raised:
        resolve_agents()
    assert raised.value.code == code


def test_schema_errors_point_at_the_file_and_line(scopes: dict[str, Path]) -> None:
    path = _write(scopes["user"], "agents", "bad", "schema_version: 1\nprovider: gpt-auto\nmodle: x\n")
    with pytest.raises(AudiaGenticError) as raised:
        resolve_agents()
    assert raised.value.details["file"] == str(path)
    assert raised.value.details["line"] == 1  # additionalProperties is reported on the mapping


def test_instructions_file_is_relative_to_its_declaring_file(scopes: dict[str, Path]) -> None:
    (scopes["project"] / "agents").mkdir(parents=True)
    (scopes["project"] / "agents" / "rules.txt").write_text("Follow the team rules.\n", encoding="utf-8")
    _write(scopes["project"], "agents", "r",
           "schema_version: 1\nprovider: gpt-auto\nmodel: chatgpt\ninstructions_file: rules.txt\n")
    assert resolve_agents()["r"].fields["instructions"] == "Follow the team rules.\n"
    _write(scopes["project"], "agents", "r",
           "schema_version: 1\nprovider: gpt-auto\nmodel: chatgpt\ninstructions_file: missing.txt\n")
    with pytest.raises(AudiaGenticError) as raised:
        resolve_agents()
    assert raised.value.code == "CFG-AGF-005"


def test_compiled_catalog_passes_existing_validators(scopes: dict[str, Path]) -> None:
    _write(scopes["user"], "agents", "reviewer-gpt-agent",
           "schema_version: 1\nextends: reviewer\nprovider: gpt-auto\nmodel: chatgpt\n")
    _write(scopes["user"], "agents", "local", "schema_version: 1\nprovider: claude\nmodel: m\ninstructions: x\n")
    document = compile_catalog(resolve_agents())
    AgentsConfigDocument.from_mapping(document)
    for section, convert, key in (("roles", role_from_dict, "role_id"),
                                  ("execution_profiles", execution_profile_from_dict, "profile_id"),
                                  ("agents", agent_definition_from_dict, "agent_id")):
        for item_id, record in document[section].items():
            convert({key: item_id, **record})
    profile = document["execution_profiles"]["reviewer-gpt-agent"]
    assert profile == {"provider_id": "gpt-auto", "instances": ["chatgpt"], "params": {},
                       "description": profile["description"], "surface_id": "gpt-auto-cdp"}


@pytest.fixture
def no_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    import audiagentic.runtime.bootstrap as bootstrap

    def fail(**kwargs):
        raise AssertionError("agent commands must not compose the application graph")

    monkeypatch.setattr(bootstrap, "build_application_graph", fail)


def test_cli_list_show_and_add(scopes: dict[str, Path], no_graph: None, capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(["agent", "add", "reviewer-gpt-agent", "--extends", "reviewer", "--provider", "gpt-auto",
                  "--model", "chatgpt", "--json"]) == 0
    written = Path(json.loads(capsys.readouterr().out)["file"])
    assert written == scopes["user"] / "agents" / "reviewer-gpt-agent.yaml"
    assert written.read_text() == "schema_version: 1\nextends: reviewer\nprovider: gpt-auto\nmodel: \"chatgpt\"\n"

    assert _main(["agent", "list", "--json"]) == 0
    assert [row["id"] for row in json.loads(capsys.readouterr().out)] == ["reviewer-gpt-agent"]
    assert _main(["agent", "show", "reviewer-gpt-agent", "--origin", "--json"]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["fields"]["surface"] == "gpt-auto-cdp" and "/model" in shown["origins"]

    assert _main(["agent", "add", "reviewer-gpt-agent", "--provider", "gpt-auto", "--model", "x"]) == 1
    assert _main(["agent", "show", "missing"]) == 1


def test_cli_add_rolls_back_an_unresolvable_agent(scopes: dict[str, Path], no_graph: None,
                                                  capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(["agent", "add", "bad", "--provider", "opencode", "--model", "m", "--scope", "project"]) == 2
    assert "CFG-AGF-003" in capsys.readouterr().out
    assert not (scopes["project"] / "agents" / "bad.yaml").exists()
