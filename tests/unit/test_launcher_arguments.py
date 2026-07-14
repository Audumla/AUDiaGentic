from __future__ import annotations

import pytest

from audiagentic.launcher import _main


def test_registered_command_rejects_unknown_arguments(capsys) -> None:
    with pytest.raises(SystemExit) as exc_info:
        _main(["component", "list", "--bad-option"])

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --bad-option" in capsys.readouterr().err
