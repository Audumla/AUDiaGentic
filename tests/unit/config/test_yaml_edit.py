"""patch_text: minimal text edits that parse to exactly the RFC 7396 result."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Any

import pytest

from audiagentic.foundation.config.merge import merged
from audiagentic.foundation.config.strict_yaml import load_settings_text
from audiagentic.foundation.config.yaml_edit import patch_text

BASE = """# header comment
schema_version: 1

providers:
  gpt-auto:   # inline note
    enabled: auto
    instances:
      one:
        project-url: https://example.test/1
  claude:
    enabled: true
# between sections
agents:
  default: reviewer
  list: [a, b]
"""


def _load(text: str) -> dict[str, Any]:
    return load_settings_text(text, Path("t.yaml")).data


def _apply(text: str, patch: dict[str, Any]) -> str:
    old = _load(text)
    out = patch_text(text, old, patch)
    assert _load(out) == merged(old, patch)
    return out


def test_other_lines_and_comments_are_untouched() -> None:
    out = _apply(BASE, {"providers": {"claude": {"enabled": False}}})
    assert out == BASE.replace("    enabled: true", "    enabled: false")


@pytest.mark.parametrize(
    "patch",
    [
        {"providers": {"gpt-auto": {"enabled": None}}},
        {"providers": {"gpt-auto": {"instances": {"two": {"project-url": "https://x"}}}}},
        {"providers": {"claude": None, "gpt-auto": None}},
        {"providers": None, "agents": None},
        {"agents": {"list": ["z"]}},
        {"agents": {"list": {"nested": 1}}},
        {"agents": {"default": {"a": {"b": 1}}}},
        {"providers": {"gpt-auto": "scalar now"}},
        {"new": {"deep": {"er": [1, {"k": None}]}}},
        {"providers": {"gpt-auto": {"instances": {"one": None}}}},
    ],
)
def test_every_patch_parses_to_the_merge_result(patch: dict[str, Any]) -> None:
    _apply(BASE, patch)


@pytest.mark.parametrize("text", ["", "# only a comment\n", "{}\n", "schema_version: 1", "a: {b: 1}\nc: 2\n", "a:\nb: 1\n"])
@pytest.mark.parametrize("patch", [{"x": {"y": 1}}, {"a": {"b": None}}, {"c": None}, {"a": {"k": 2}}, {"a": 5}])
def test_small_and_unusual_documents(text: str, patch: dict[str, Any]) -> None:
    _apply(text, patch)


def test_keys_that_would_be_mistyped_are_quoted() -> None:
    out = _apply("schema_version: 1\n", {"true": 1, "12": 2, "a b": 3, "ok-key": 4})
    assert _load(out)["true"] == 1 and _load(out)["12"] == 2


def test_windows_line_endings_are_kept() -> None:
    text = BASE.replace("\n", "\r\n")
    out = _apply(text, {"providers": {"pi": {"enabled": True}}})
    assert "\r\n" in out and "\n" not in out.replace("\r\n", "")


@pytest.mark.parametrize("seed", range(6))
def test_random_patches_always_match_the_merge_result(seed: int) -> None:
    rng = random.Random(seed)
    names = ["a", "b", "c", "providers", "gpt-auto", "enabled", "x y", "1"]

    def value(depth: int) -> Any:
        roll = rng.random()
        if depth > 2 or roll < 0.35:
            return rng.choice([None, True, False, 1, 2.5, "s", "x y", "", [1, 2], [], {}])
        return {rng.choice(names): value(depth + 1) for _ in range(rng.randint(0, 3))}

    text = BASE
    for _ in range(80):
        patch = {rng.choice(names): value(0) for _ in range(rng.randint(1, 3))}
        text = _apply(text, patch)
