import json
import subprocess
import sys

from audiagentic.components.providers.adapters.claude import join
from audiagentic.components.providers.services.qualification import live
from audiagentic.components.providers.services.qualification.probes.env import (
    ENV_ALLOWLIST,
    disposable_env,
)


def test_the_disposable_environment_inherits_only_the_allowlist_and_roots_everything_in_the_temp_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid")
    env = disposable_env(tmp_path, extra_dirs=("tool-home",), extra={"TOOL_HOME": str(tmp_path / "tool-home")})
    assert set(env) <= {*ENV_ALLOWLIST, "HOME", "TMPDIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
                        "XDG_STATE_HOME", "TOOL_HOME"}
    assert env["HOME"] == str(tmp_path / "home") and (tmp_path / "tool-home").is_dir()
    assert all(str(tmp_path) in value for key, value in env.items() if key not in ENV_ALLOWLIST)
    assert disposable_env(tmp_path, tmp=tmp_path / "exec")["TMPDIR"] == str(tmp_path / "exec")


def _fake_run(monkeypatch, returncode=0, stdout=b"[]"):
    monkeypatch.setattr(join.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, returncode, stdout, b""))


def test_the_session_listing_must_exit_zero_and_be_a_bounded_list_of_objects(tmp_path, monkeypatch):
    _fake_run(monkeypatch, stdout=json.dumps([{"pid": 1}]).encode())
    assert join.list_sessions({}, tmp_path) == [{"pid": 1}]
    for bad in (dict(returncode=1), dict(stdout=b"not json"), dict(stdout=b'{"pid": 1}'), dict(stdout=b"[1]"),
                dict(stdout=b"[" + b" " * (join._MAX_LISTING_BYTES + 1) + b"]")):
        _fake_run(monkeypatch, **bad)
        assert join.list_sessions({}, tmp_path) is None


def test_the_suite_digest_covers_the_shared_probe_helpers(tmp_path):
    probe = tmp_path / "probe.py"
    probe.write_text("a = 1\n")
    (tmp_path / "stub_model.py").write_text("x = 1\n")
    first = live._suite_digest(probe)
    (tmp_path / "stub_model.py").write_text("x = 2\n")
    assert live._suite_digest(probe) != first and sys  # a changed helper changes the suite identity
