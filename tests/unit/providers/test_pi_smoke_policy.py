"""Smoke policy must wrap the actual Pi executable, not replace its output."""

import os
import shlex

import pytest

from tests.helpers.pi_smoke import restrict_smoke_pi


@pytest.mark.parametrize("tools", [None, "bash"])
def test_smoke_wrapper_preserves_real_binary_and_native_policy(tmp_path, monkeypatch, tools):
    real = str(tmp_path / "real pi")
    monkeypatch.setattr("tests.helpers.pi_smoke.shutil.which", lambda _name: real)
    previous = os.environ.get("PATH", "")
    restrict_smoke_pi(tmp_path, monkeypatch, tools=tools)
    script = (tmp_path / "smoke-bin" / "pi").read_text(encoding="utf-8")
    argv = shlex.split(script.splitlines()[1])
    assert argv[:2] == ["exec", real]
    assert argv[-1] == "$@"
    assert argv[argv.index("--thinking") + 1] == "off"
    assert "--no-extensions" in argv
    if tools:
        assert argv[argv.index("--tools") + 1] == tools
        assert "--no-tools" not in argv
    else:
        assert "--no-tools" in argv
    assert os.environ["PATH"] == str(tmp_path / "smoke-bin") + os.pathsep + previous
