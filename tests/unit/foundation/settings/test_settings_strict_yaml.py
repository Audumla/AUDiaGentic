"""The settings loader accepts only a JSON-compatible YAML 1.2 core subset."""
from __future__ import annotations

from pathlib import Path

import pytest

from audiagentic.foundation.config.strict_yaml import load_settings_file, load_settings_text
from audiagentic.foundation.contracts.errors import AudiaGenticError


def _load(text: str) -> dict:
    return load_settings_text(text, Path("settings.yaml")).data


def _rejects(text: str, code: str = "CFG-SET-003") -> AudiaGenticError:
    with pytest.raises(AudiaGenticError) as raised:
        load_settings_text(text, Path("settings.yaml"))
    assert raised.value.code == code
    return raised.value


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v: yes", "yes"), ("v: no", "no"), ("v: on", "on"), ("v: off", "off"),  # YAML 1.1 booleans stay strings
        ("v: true", True), ("v: False", False),
        ("v: 012", 12), ("v: 0o12", 10), ("v: 0x12", 18), ("v: -7", -7),  # YAML 1.2 core integers
        ("v: 1.5", 1.5), ("v: 1e3", 1000.0),
        ("v: 2026-10-28", "2026-10-28"),  # no timestamps
        ("v: ~", None), ("v:", None), ("v: null", None),
        ("v: '1'", "1"), ('v: "true"', "true"),  # quoted scalars are strings
        ("v: |\n  line\n", "line\n"),
    ],
)
def test_scalars_follow_yaml_12_core(text: str, expected: object) -> None:
    value = _load(text)["v"]
    assert value == expected
    assert type(value) is type(expected)


def test_nested_collections_and_positions() -> None:
    document = load_settings_text("a:\n  b: [1, x]\n  c:\n    - d: 2\n", Path("s.yaml"))
    assert document.data == {"a": {"b": [1, "x"], "c": [{"d": 2}]}}
    assert (document.positions["/a/b/1"].line, document.positions["/a/b/1"].column) == (2, 10)
    assert document.positions["/a/c/0/d"].line == 4


@pytest.mark.parametrize(
    "text",
    [
        "a: .nan", "a: .inf", "a: -.Inf",
        "a: &anchor 1\nb: 2",
        "a: &x [1]\nb: *x",
        "a: !!str 1", "a: !custom x", "a: !!python/object:os.system x", "a: ! x",
        "a: 1\na: 2",
        "a: 1\n'a': 2",  # duplicate after scalar normalisation
        "1: x", "true: x", "~: x", "? [a]\n: x",
        "a: 1\n---\nb: 2",
        "- a\n- b",
    ],
)
def test_disallowed_yaml_is_rejected(text: str) -> None:
    _rejects(text)


def test_alias_bomb_is_rejected_before_expansion() -> None:
    bomb = 'a: &a ["x","x","x","x","x","x","x","x","x"]\n' + "".join(
        f"{chr(98 + i)}: &{chr(98 + i)} [*{chr(97 + i)},*{chr(97 + i)},*{chr(97 + i)},*{chr(97 + i)}]\n" for i in range(8)
    )
    _rejects(bomb)


def test_errors_report_file_line_column_and_pointer() -> None:
    error = _rejects("a:\n  b: 1\n  b: 2\n")
    assert error.details["file"] == "settings.yaml"
    assert (error.details["line"], error.details["column"], error.details["pointer"]) == (3, 3, "/a/b")


def test_syntax_error_has_position() -> None:
    error = _rejects("a: [1, 2\nb: 3\n", code="CFG-SET-002")
    assert error.details["line"] is not None


def test_too_deep_documents_are_rejected() -> None:
    _rejects("a: " + "[" * 70 + "]" * 70)


def test_file_level_checks(tmp_path: Path) -> None:
    good = tmp_path / "ok.yaml"
    good.write_bytes("\ufeffa: 1\n".encode())
    assert load_settings_file(good).data == {"a": 1}
    bad = tmp_path / "bad.yaml"
    bad.write_bytes(b"a: \xff\n")
    with pytest.raises(AudiaGenticError) as raised:
        load_settings_file(bad)
    assert raised.value.code == "CFG-SET-001"
    big = tmp_path / "big.yaml"
    big.write_bytes(b"a: " + b"x" * (1024 * 1024))
    with pytest.raises(AudiaGenticError) as raised:
        load_settings_file(big)
    assert raised.value.code == "CFG-SET-001"
    with pytest.raises(AudiaGenticError) as raised:
        load_settings_file(tmp_path / "missing.yaml")
    assert raised.value.code == "CFG-SET-001"


def test_empty_file_is_empty_mapping() -> None:
    assert _load("") == {}
    assert _load("# only a comment\n") == {}
