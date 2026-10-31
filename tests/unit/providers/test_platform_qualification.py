"""CFG07: local platform qualification records and the resolver that accepts them."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest
import yaml

from audiagentic.commands import qualify as qualify_command
from audiagentic.components.providers.contracts.session_surface import SurfaceHint
from audiagentic.components.providers.providers_api import resolve_session_surface
from audiagentic.components.providers.services.config.provider_config import set_provider_enabled
from audiagentic.components.providers.services.qualification import platform_records as records
from audiagentic.components.providers.services.qualification import qualifier
from audiagentic.foundation.transports.session_surface import SurfaceResolutionOutcome

FOREIGN = "linux-arm64"  # gpt-auto ships vendor evidence for windows-amd64 and linux-amd64 only


@pytest.fixture
def foreign_platform(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(qualifier, "release_platform_name", lambda: FOREIGN)
    set_provider_enabled(tmp_path, "gpt-auto", enabled=True)
    return tmp_path


def _resolve(project: Path):
    return resolve_session_surface(project, "gpt-auto", SurfaceHint(surface_id="gpt-auto-cdp", platform_hint=FOREIGN))


def test_an_unqualified_platform_is_not_resolvable(foreign_platform: Path) -> None:
    surface = _resolve(foreign_platform)
    assert surface.validation.reason == "no-platform-match"


def test_qualify_makes_the_surface_resolvable_with_no_package_edit(foreign_platform: Path) -> None:
    [result] = qualifier.qualify("gpt-auto", "gpt-auto-cdp")
    assert result["result"] == "qualified"
    surface = _resolve(foreign_platform)
    assert surface.validation.reason == ""
    assert surface.validation.outcome == SurfaceResolutionOutcome.SUPPORTED


def test_the_record_binds_fingerprint_version_spec_and_evidence() -> None:
    [result] = qualifier.qualify("gpt-auto", "gpt-auto-cdp")
    record = yaml.safe_load(Path(result["path"]).read_text(encoding="utf-8"))
    for key in ("provider-id", "surface-id", "platform", "fingerprint", "package-version", "spec-version",
                "result", "qualified-at", "environment", "evidence-digest"):
        assert key in record
    assert record["package-version"] == records.package_version()
    assert record["spec-version"] == records.SPEC_VERSION


def test_one_platforms_record_never_stands_in_for_another(foreign_platform: Path, monkeypatch) -> None:
    qualifier.qualify("gpt-auto", "gpt-auto-cdp")
    other = records.check_record("gpt-auto", "gpt-auto-cdp", "linux-riscv64")
    assert other.reason == "unqualified"
    surface = resolve_session_surface(
        foreign_platform, "gpt-auto", SurfaceHint(surface_id="gpt-auto-cdp", platform_hint="linux-riscv64"))
    assert surface.validation.reason == "no-platform-match"


def _edit(provider: str, surface: str, platform: str, **changes) -> None:
    path = records.record_path(provider, surface, platform)
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    record.update(changes)
    path.write_text(yaml.safe_dump(record), encoding="utf-8")


@pytest.mark.parametrize(("changes", "reason"), [
    ({"package-version": "0.0.1"}, "qualification-stale"),
    ({"spec-version": 99}, "qualification-stale"),
    ({"result": "failed"}, "qualification-failed"),
])
def test_stale_or_failed_records_are_rejected(foreign_platform: Path, changes, reason) -> None:
    qualifier.qualify("gpt-auto", "gpt-auto-cdp")
    _edit("gpt-auto", "gpt-auto-cdp", FOREIGN, **changes)
    assert _resolve(foreign_platform).validation.reason == reason


def test_a_changed_implementation_fingerprint_is_stale(foreign_platform: Path) -> None:
    qualifier.qualify("gpt-auto", "gpt-auto-cdp")
    _edit("gpt-auto", "gpt-auto-cdp", FOREIGN, fingerprint={"adapter-ref": "some.other:factory"})
    assert _resolve(foreign_platform).validation.reason == "qualification-stale"


def test_a_corrupt_record_fails_closed(foreign_platform: Path) -> None:
    qualifier.qualify("gpt-auto", "gpt-auto-cdp")
    records.record_path("gpt-auto", "gpt-auto-cdp", FOREIGN).write_text("{not: [valid", encoding="utf-8")
    assert _resolve(foreign_platform).validation.reason == "qualification-invalid"


def test_a_record_for_the_wrong_location_is_invalid() -> None:
    qualifier.qualify("gpt-auto", "gpt-auto-cdp")
    here = qualifier.release_platform_name()
    path = records.record_path("gpt-auto", "gpt-auto-cdp", here)
    record = yaml.safe_load(path.read_text(encoding="utf-8"))
    other = records.record_path("gpt-auto", "gpt-auto-cdp", "linux-s390x")
    other.parent.mkdir(parents=True, exist_ok=True)
    other.write_text(yaml.safe_dump(record), encoding="utf-8")
    assert records.check_record("gpt-auto", "gpt-auto-cdp", "linux-s390x").reason == "invalid"


def test_requalifying_replaces_the_record_atomically(foreign_platform: Path) -> None:
    first = qualifier.qualify("gpt-auto", "gpt-auto-cdp")[0]["path"]
    second = qualifier.qualify("gpt-auto", "gpt-auto-cdp")[0]["path"]
    assert first == second
    assert [p.name for p in Path(first).parent.iterdir()] == [f"{FOREIGN}.yaml"]


def test_unsafe_path_components_are_refused() -> None:
    with pytest.raises(ValueError):
        records.record_path("../x", "s", "p")


def test_unknown_provider_or_surface_is_named() -> None:
    with pytest.raises(KeyError):
        qualifier.qualify("no-such-provider")
    with pytest.raises(KeyError):
        qualifier.qualify("gpt-auto", "no-such-surface")


def test_a_missing_cli_fails_the_record(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(records, "current_fingerprint", lambda *a, **k: {"executable-digest": None})
    monkeypatch.setattr(qualifier.records, "current_fingerprint", lambda *a, **k: {"executable-digest": None})
    [result] = qualifier.qualify("codex", None)[:1]
    assert result["result"] == "failed"
    assert any(check["name"] == "implementation" and not check["ok"] for check in result["checks"])


def test_command_reports_results_and_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(provider="gpt-auto", provider_option=None, surface="gpt-auto-cdp", as_json=True)
    assert qualify_command.run_qualify_command(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["results"][0]["result"] == "qualified"
    args.provider = "nope"
    assert qualify_command.run_qualify_command(args) == qualify_command.EXIT_UNKNOWN
