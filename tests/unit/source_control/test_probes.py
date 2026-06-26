from __future__ import annotations

import subprocess

from audiagentic.components.source_control import probes


def test_gh_mcp_available_decodes_help_with_utf8_replace(monkeypatch) -> None:
    probes.gh_mcp_available.cache_clear()
    monkeypatch.setattr(probes, "tool_available", lambda name: name == "gh")
    monkeypatch.setattr(probes.Path, "home", lambda: probes.Path(r"Z:\no-such-home"))
    monkeypatch.setattr(probes.os, "environ", {})

    class _Result:
        def __init__(self, returncode: int, stdout: str = "") -> None:
            self.returncode = returncode
            self.stdout = stdout

    calls: list[dict[str, object]] = []

    def _fake_run(cmd, **kwargs):
        calls.append(kwargs)
        if cmd[:3] == ["gh", "extension", "list"]:
            return _Result(1, "")
        return _Result(0, "serve")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    assert probes.gh_mcp_available() is True
    assert any(kwargs.get("encoding") == "utf-8" for kwargs in calls)
    assert any(kwargs.get("errors") == "replace" for kwargs in calls)
