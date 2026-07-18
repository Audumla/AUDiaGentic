from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.io import read_text_with_retry


def test_read_text_retries_a_transient_sharing_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "record.json"
    path.write_text("ready", encoding="utf-8")
    original = Path.read_text
    calls = 0

    def transient(target: Path, *args, **kwargs) -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise PermissionError("sharing violation")
        return original(target, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", transient)

    assert read_text_with_retry(path) == "ready"
    assert calls == 3


def test_read_text_does_not_hide_a_persistent_permission_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "record.json"
    path.write_text("ready", encoding="utf-8")
    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )

    with pytest.raises(PermissionError, match="denied"):
        read_text_with_retry(path)
