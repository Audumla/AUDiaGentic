"""Host-safety net for memory tests.

The memory component provisions Hindsight-owned artifacts under the OS home
(``~/.hindsight/*``). The global autouse fixture only isolates
``AUDIAGENTIC_HOME``, not the OS home, so without this a recipe/provision test
would read and overwrite the developer's real ``~/.hindsight`` files. This
redirects ``expanduser`` (USERPROFILE/HOME and the Windows HOMEDRIVE+HOMEPATH
pair) to a per-test tmp dir. Tests that need to assert on the isolated home set
these same vars to their own ``tmp_path`` explicitly.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_os_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path_factory.mktemp("os-home")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("HOMEDRIVE", home.drive or "")
    monkeypatch.setenv("HOMEPATH", str(home)[len(home.drive):] if home.drive else str(home))
