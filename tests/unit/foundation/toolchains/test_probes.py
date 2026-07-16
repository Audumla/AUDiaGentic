from __future__ import annotations

import json
import sys

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.toolchains.probes import (
    CommandProbe,
    CompositeHealthCheck,
    ConfigKeyCheck,
    FileExistsCheck,
    ProbeResult,
    check_with_retry,
    probe_from_spec,
)


def test_file_exists_check_pass_and_fail(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello world", encoding="utf-8")
    assert FileExistsCheck(f).check().passed is True
    assert FileExistsCheck(tmp_path / "missing").check().passed is False


def test_file_exists_content_pattern(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("token = abc", encoding="utf-8")
    assert FileExistsCheck(f, content_pattern=r"token\s*=").check().passed is True
    assert FileExistsCheck(f, content_pattern=r"nope").check().passed is False


def test_config_key_check_deep_path(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"a": {"b": {"c": 7}}}), encoding="utf-8")
    assert ConfigKeyCheck(cfg, ("a", "b", "c")).check().passed is True
    assert ConfigKeyCheck(cfg, ("a", "b", "c"), expected_value=7).check().passed is True
    assert ConfigKeyCheck(cfg, ("a", "b", "c"), expected_value=8).check().passed is False
    assert ConfigKeyCheck(cfg, ("a", "x")).check().passed is False


def test_command_probe_exit_code():
    probe = CommandProbe((sys.executable, "-c", "import sys; sys.exit(0)"))
    assert probe.check().passed is True
    bad = CommandProbe((sys.executable, "-c", "import sys; sys.exit(3)"))
    assert bad.check().passed is False


def test_command_probe_output_pattern():
    probe = CommandProbe(
        (sys.executable, "-c", "print('VERSION 1.2.3')"),
        output_pattern=r"VERSION \d+\.\d+\.\d+",
    )
    assert probe.check().passed is True


def test_command_probe_missing_executable():
    assert CommandProbe(("definitely-not-a-real-binary-xyz",)).check().passed is False


def _const(passed: bool):
    class _P:
        def check(self, context=None):
            return ProbeResult(passed, "const")

    return _P()


def test_composite_and_short_circuits():
    res = CompositeHealthCheck((_const(True), _const(False), _const(True)), mode="and").check()
    assert res.passed is False
    # short-circuit: stops at the failing second check
    assert len(res.sub_results) == 2


def test_composite_or_short_circuits():
    res = CompositeHealthCheck((_const(False), _const(True), _const(False)), mode="or").check()
    assert res.passed is True
    assert len(res.sub_results) == 2


def test_composite_atleast_threshold():
    checks = (_const(True), _const(False), _const(True), _const(False))
    assert CompositeHealthCheck(checks, mode="atleast", threshold=2).check().passed is True
    assert CompositeHealthCheck(checks, mode="atleast", threshold=3).check().passed is False


def test_check_with_retry_eventually_passes():
    state = {"calls": 0}

    class _Flaky:
        def check(self, context=None):
            state["calls"] += 1
            return ProbeResult(state["calls"] >= 3, "flaky")

    res = check_with_retry(_Flaky(), retries=5)
    assert res.passed is True
    assert state["calls"] == 3


# ---------------------------------------------------------------------------
# probe_from_spec — the single production parser for dependency probe syntax
# ---------------------------------------------------------------------------

def test_probe_from_spec_binary(monkeypatch):
    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.detect.tool_available",
        lambda name: name == "present",
    )
    assert probe_from_spec("binary:present").check().passed is True
    assert probe_from_spec("binary:absent").check().passed is False


def test_probe_from_spec_all_binaries_requires_every_entry(monkeypatch):
    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.detect.tool_available",
        lambda name: name in {"a", "b"},
    )
    assert probe_from_spec("all-binaries:a,b").check().passed is True
    assert probe_from_spec("all-binaries:a,missing").check().passed is False


def test_probe_from_spec_all_binaries_trims_empty_items(monkeypatch):
    seen: list[str] = []

    def _available(name: str) -> bool:
        seen.append(name)
        return True

    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.detect.tool_available", _available
    )
    assert probe_from_spec("all-binaries: a , ,b ,").check().passed is True
    assert seen == ["a", "b"]


def test_probe_from_spec_toolchain_uv(monkeypatch):
    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.detect.uv_available", lambda: True
    )
    assert probe_from_spec("toolchain:uv").check().passed is True


def test_probe_from_spec_path_expands_tilde(tmp_path, monkeypatch):
    target = tmp_path / "marker.txt"
    target.write_text("x", encoding="utf-8")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))

    assert probe_from_spec(f"path:{target}").check().passed is True
    assert probe_from_spec("path:~/marker.txt").check().passed is True
    assert probe_from_spec("path:~/absent.txt").check().passed is False


def test_probe_from_spec_command_success_and_failure(monkeypatch):
    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.probes.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )

    class _Result:
        def __init__(self, rc):
            self.returncode = rc
            self.stdout = ""
            self.stderr = ""

    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.probes.subprocess.run",
        lambda *a, **k: _Result(0),
    )
    assert probe_from_spec("command:tool --version").check().passed is True

    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.probes.subprocess.run",
        lambda *a, **k: _Result(1),
    )
    assert probe_from_spec("command:tool --version").check().passed is False


def test_probe_from_spec_command_uses_ten_second_timeout(monkeypatch):
    seen: dict[str, object] = {}

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(*args, **kwargs):
        seen.update(kwargs)
        return _Result()

    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.probes.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )
    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.probes.subprocess.run", _fake_run
    )

    assert probe_from_spec("command:tool --version").check().passed is True
    assert seen["timeout"] == 10
    assert seen["encoding"] == "utf-8"
    assert seen["errors"] == "replace"


def test_probe_from_spec_command_timeout_is_not_passing(monkeypatch):
    import subprocess as _sp

    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.probes.shutil.which",
        lambda name: f"/usr/bin/{name}",
    )

    def _raise(*a, **k):
        raise _sp.TimeoutExpired(cmd="tool", timeout=10)

    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.probes.subprocess.run", _raise
    )
    result = probe_from_spec("command:tool --version").check()
    assert result.passed is False
    assert "timed out" in result.detail


def test_probe_from_spec_command_rejects_shell_compound():
    with pytest.raises(AudiaGenticError) as excinfo:
        probe_from_spec("command:tool --version | grep x")
    assert excinfo.value.code == "VAL-CMD-001"


@pytest.mark.parametrize("returns", [True, False])
def test_probe_from_spec_custom_wraps_resolved_callable(monkeypatch, returns):
    # resolve_ref binds the target at parse time, so patch the resolver itself
    # to keep this independent of what is installed on the host.
    monkeypatch.setattr(
        "audiagentic.foundation.refs.resolve_ref", lambda ref: (lambda: returns)
    )
    probe = probe_from_spec("custom:some.module:some_predicate")
    assert probe.check().passed is returns


def test_probe_from_spec_custom_rejects_non_callable(monkeypatch):
    monkeypatch.setattr(
        "audiagentic.foundation.refs.resolve_ref", lambda ref: "not-callable"
    )
    with pytest.raises(AudiaGenticError) as excinfo:
        probe_from_spec("custom:some.module:some_value")
    assert excinfo.value.code == "VAL-DEP-001"


def test_probe_from_spec_custom_unresolvable_ref():
    with pytest.raises(AudiaGenticError) as excinfo:
        probe_from_spec("custom:audiagentic.foundation.toolchains.detect:no_such_name")
    assert excinfo.value.code == "VAL-DEP-001"


def test_probe_from_spec_predicate_failure_detail_is_redacted(monkeypatch):
    def _boom(name):
        raise RuntimeError("token=sk-secret-value failed")

    monkeypatch.setattr(
        "audiagentic.foundation.toolchains.detect.tool_available", _boom
    )
    result = probe_from_spec("binary:thing").check()
    assert result.passed is False
    assert "sk-secret-value" not in result.detail


@pytest.mark.parametrize(
    "spec",
    [
        "unknown:thing",
        "binary:",
        "all-binaries:",
        "all-binaries: , ",
        "path:",
        "command:",
        "custom:",
        "toolchain:npm",
        "",
    ],
)
def test_probe_from_spec_rejects_malformed_specs(spec):
    with pytest.raises(AudiaGenticError) as excinfo:
        probe_from_spec(spec)
    assert excinfo.value.code == "VAL-DEP-001"
