"""CFG08: doctor discovers component checks, is read-only; setup is idempotent."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from audiagentic.foundation.lifecycle.doctor import (
    FAIL,
    OK,
    DoctorContext,
    declared_checks,
    run_checks,
)
from audiagentic.launcher import _main


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    import audiagentic.runtime.bootstrap as bootstrap

    def fail(**kwargs):
        raise AssertionError("doctor/setup must not compose the application graph")

    monkeypatch.setattr(bootstrap, "build_application_graph", fail)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg-state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.delenv("AUDIAGENTIC_PROJECT", raising=False)
    monkeypatch.delenv("AUDIAGENTIC_CONFIG", raising=False)
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    monkeypatch.chdir(root)
    return {"root": root, "user": tmp_path / "xdg" / "audiagentic", "tmp": tmp_path}


def _by_check(results) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for result in results:
        grouped.setdefault(result.check, []).append(result)
    return grouped


def test_checks_are_declared_by_their_components() -> None:
    owners = {check.check_id: check.component for check in declared_checks()}
    assert owners["settings.valid"] == "foundation"
    assert owners["package.data"] == "foundation"
    assert owners["project.identity"] == "project"
    assert owners["agents.files"] == "agents"


def test_doctor_is_read_only(env: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    before = sorted(env["tmp"].rglob("*"))
    assert _main(["doctor", "--json"]) == 0
    assert sorted(env["tmp"].rglob("*")) == before
    checks = {check["check"]: check for check in json.loads(capsys.readouterr().out)["checks"]}
    assert checks["package.data"]["status"] == OK
    assert checks["project.identity"]["status"] == "warn"  # no remote: name is the checkout directory


def test_invalid_settings_fail_with_exit_2(env: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    settings = env["root"] / ".audiagentic" / "settings.yaml"
    settings.parent.mkdir()
    settings.write_text("schema_version: 1\nbogus: 1\n", encoding="utf-8")
    assert _main(["doctor", "--json"]) == 2
    out = json.loads(capsys.readouterr().out)
    failed = [check for check in out["checks"] if check["status"] == FAIL]
    assert failed[0]["check"] == "settings.valid" and "bogus" in failed[0]["message"]
    assert "config validate" in failed[0]["fix"]


def test_agent_provider_availability(env: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    import audiagentic.components.providers.providers_api as providers_api

    agents = env["user"] / "agents"
    agents.mkdir(parents=True)
    (agents / "r.yaml").write_text("schema_version: 1\nextends: reviewer\nprovider: gpt-auto\nmodel: chatgpt\n")
    monkeypatch.setattr(providers_api, "is_provider_enabled_for_launch", lambda root, provider: True)
    monkeypatch.setattr(providers_api, "check_provider_availability", lambda root, provider: (False, "CDP down"))
    checks = _by_check(run_checks(DoctorContext(None)))
    assert checks["agents.files"][0].status == OK
    assert checks["provider.gpt-auto"][0].status == FAIL
    assert "CDP down" in checks["provider.gpt-auto"][0].fix
    monkeypatch.setattr(providers_api, "check_provider_availability", lambda root, provider: (True, "CDP answers"))
    assert _by_check(run_checks(DoctorContext(None)))["provider.gpt-auto"][0].status == OK


def test_a_crashing_or_erroring_check_is_reported_not_raised(env: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    from audiagentic.foundation.paths.names import get_package_components_config_dir

    extra = env["tmp"] / "components"
    (extra / "demo" / "doctor").mkdir(parents=True)
    (extra / "demo" / "doctor" / "checks.yaml").write_text(
        "checks:\n"
        "  - id: demo.crash\n    ref: json:loads\n"
        "  - id: demo.error\n    ref: audiagentic.foundation.config.settings:discover_project_root\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUDIAGENTIC_COMPONENT_CONFIG_DIRS", f"{get_package_components_config_dir()},{extra}")
    monkeypatch.setenv("AUDIAGENTIC_PROJECT", str(env["tmp"] / "missing"))
    checks = _by_check(run_checks(DoctorContext(None)))
    assert checks["demo.crash"][0].status == FAIL and "crashed" in checks["demo.crash"][0].message
    assert checks["project.identity"][0].status == FAIL
    assert checks["project.identity"][0].message.startswith("CFG-SET-005")


def test_setup_creates_user_settings_once(env: dict[str, Path], capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(["setup", "--json"]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["created"] == [str(env["user"] / "settings.yaml")]
    assert (env["user"] / "settings.yaml").read_text().endswith("schema_version: 1\n")
    assert _main(["setup", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["created"] == []


def test_clean_home_warns_about_the_catalog_instead_of_failing(env: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(env["tmp"] / "agentic-home"))
    checks = _by_check(run_checks(DoctorContext(None)))
    assert checks["agents.files"][0].status == "warn"
    assert checks["agents.catalog"][0].status == "warn"
    assert "agent add" in checks["agents.catalog"][0].fix
    assert not [r for rs in checks.values() for r in rs if r.status == FAIL]


def test_an_invalid_legacy_catalog_still_fails(env: dict[str, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    home = env["tmp"] / "agentic-home"
    (home / "config").mkdir(parents=True)
    (home / "config" / "agents.yaml").write_text("not: [valid", encoding="utf-8")
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(home))
    assert _by_check(run_checks(DoctorContext(None)))["agents.catalog"][0].status == FAIL


def test_gpt_auto_on_an_embedded_gateway_is_flagged_with_the_fix(
    env: dict[str, Path], monkeypatch: pytest.MonkeyPatch,
) -> None:
    import audiagentic.components.providers.providers_api as providers_api

    agents = env["user"] / "agents"
    agents.mkdir(parents=True)
    (agents / "r.yaml").write_text("schema_version: 1\nextends: reviewer\nprovider: gpt-auto\nmodel: chatgpt\n")
    monkeypatch.setenv("AUDIAGENTIC_HOME", str(env["tmp"] / "agentic-home"))
    monkeypatch.setattr(providers_api, "is_provider_enabled_for_launch", lambda root, provider: True)
    monkeypatch.setattr(providers_api, "check_provider_availability", lambda root, provider: (True, "CDP answers"))
    monkeypatch.delenv("AUDIAGENTIC_GATEWAY_MODE", raising=False)
    warned = _by_check(run_checks(DoctorContext(None)))["agents.gateway"][0]
    assert warned.status == "warn" and "gateway.implementation" in warned.fix

    env["user"].mkdir(parents=True, exist_ok=True)
    (env["user"] / "settings.yaml").write_text("schema_version: 1\ngateway:\n  implementation: automatic\n")
    assert _by_check(run_checks(DoctorContext(None)))["agents.gateway"][0].status == OK
