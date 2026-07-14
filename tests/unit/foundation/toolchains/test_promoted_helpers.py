"""Tests for helpers promoted from hindsight recipes to foundation (HM20)."""
from __future__ import annotations

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.steps import build_steps_from_defs, lenient_substitute
from audiagentic.foundation.toolchains.detect import platform_allowed, platform_key
from audiagentic.foundation.toolchains.probes import safe_command_parts


class TestSafeCommandParts:
    def test_splits_simple_command(self) -> None:
        assert safe_command_parts("git status --short") == ["git", "status", "--short"]

    @pytest.mark.parametrize("bad", ["a | b", "a && b", "a; b", "a > f", "a < f"])
    def test_rejects_compound_shell_syntax(self, bad: str) -> None:
        # VAL-CMD-001 replaces the original REC-ML-001, which used an
        # unregistered prefix and would have crashed with ValueError if hit.
        with pytest.raises(AudiaGenticError, match="VAL-CMD-001"):
            safe_command_parts(bad)


class TestLenientSubstitute:
    def test_replaces_known_placeholders(self) -> None:
        out = lenient_substitute("curl {URL}/api --token {TOKEN}", {"URL": "http://x", "TOKEN": ""})
        assert out == "curl http://x/api --token "

    def test_leaves_unknown_placeholders_literal(self) -> None:
        assert lenient_substitute("run {MYSTERY}", {"URL": "x"}) == "run {MYSTERY}"

    def test_empty_text_passthrough(self) -> None:
        assert lenient_substitute("", {"URL": "x"}) == ""


class TestPlatformAllowed:
    def test_empty_constraints_allow_all(self) -> None:
        assert platform_allowed([]) is True

    def test_current_platform_matches(self) -> None:
        assert platform_allowed([platform_key()]) is True

    def test_other_platforms_do_not_match(self) -> None:
        others = {"darwin", "linux", "win"} - {platform_key()}
        assert platform_allowed(sorted(others)) is False

    def test_unknown_key_never_matches_and_warns(self, caplog) -> None:
        import logging

        with caplog.at_level(logging.WARNING):
            assert platform_allowed(["macOS"]) is False
        assert any("unknown platform constraint" in r.message for r in caplog.records)


class TestBuildStepsFromDefs:
    def test_assigns_sequential_ids_when_missing(self) -> None:
        steps = build_steps_from_defs(
            [
                {"type": "shell", "command": ["echo", "one"]},
                {"type": "shell", "id": "named", "command": ["echo", "two"]},
            ],
            {},
        )
        assert steps[0].id == "step-0"
        assert steps[1].id == "named"

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(AudiaGenticError, match="VAL-STEP"):
            build_steps_from_defs([{"type": "nope"}], {})
