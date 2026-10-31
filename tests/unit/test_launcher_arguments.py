from __future__ import annotations

import pytest

from audiagentic.launcher import _main


def test_registered_command_rejects_unknown_arguments(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _main(["component", "list", "--bad-option"])

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --bad-option" in capsys.readouterr().err


def test_bare_invocation_prints_management_help_without_launching(tmp_path, monkeypatch, capsys) -> None:
    import audiagentic.runtime.bootstrap as bootstrap

    def fail(**kwargs):
        raise AssertionError("bare invocation must not compose the application graph")

    monkeypatch.setattr(bootstrap, "build_application_graph", fail)
    monkeypatch.chdir(tmp_path)

    assert _main([]) == 0

    out = capsys.readouterr().out
    assert "usage: audiagentic" in out
    assert "audiagentic mcp install MCP_ID" in out
    assert list(tmp_path.iterdir()) == []  # No provider probing or surface writes.


@pytest.mark.parametrize("flag", ["--version", "-V"])
def test_version_prints_and_exits_without_launching(flag, tmp_path, monkeypatch, capsys) -> None:
    import audiagentic.runtime.bootstrap as bootstrap
    from audiagentic.runtime.update.checker import current_version

    def fail(**kwargs):
        raise AssertionError("--version must not compose the application graph")

    monkeypatch.setattr(bootstrap, "build_application_graph", fail)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        _main([flag])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"audiagentic {current_version()}"
    assert list(tmp_path.iterdir()) == []  # No provider probing or surface writes.
