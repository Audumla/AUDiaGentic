"""Characterization tests for foundation.workflow.actions.render (EDJ21).

Expected values here come from the CURRENT implementation, not desired
behavior. They exist to gate any consolidation onto foundation.templates:
if a migration cannot reproduce every case below, the migration stops.
"""
from __future__ import annotations

import pytest

from audiagentic.foundation.contracts.errors import AudiaGenticError
from audiagentic.foundation.workflow.actions import render


class TestWholePlaceholderTypePreservation:
    def test_string_value(self):
        assert render("{name}", {"name": "abc"}) == "abc"

    def test_int_value_preserved_typed(self):
        assert render("{count}", {"count": 7}) == 7

    def test_bool_value_preserved_typed(self):
        assert render("{flag}", {"flag": True}) is True

    def test_dict_value_preserved_typed(self):
        payload = {"a": 1}
        assert render("{data}", {"data": payload}) is payload

    def test_list_value_preserved_typed(self):
        items = [1, 2]
        assert render("{items}", {"items": items}) is items

    def test_none_value_preserved(self):
        assert render("{maybe}", {"maybe": None}) is None


class TestMixedStringCoercion:
    def test_mixed_text_uses_str_format(self):
        assert render("id-{n}", {"n": 42}) == "id-42"

    def test_multiple_placeholders(self):
        assert render("{a}-{b}", {"a": "x", "b": "y"}) == "x-y"

    def test_format_spec_supported(self):
        # str.format semantics: format specs work in mixed strings
        assert render("n={n:03d}!", {"n": 7}) == "n=007!"

    def test_literal_braces_escaping(self):
        # str.format semantics: {{ }} render as literal braces
        assert render("keep {{these}} {v}", {"v": "x"}) == "keep {these} x"

    def test_dict_value_coerced_via_str(self):
        # str.format calls str() on the value — not JSON
        assert render("d={d}!", {"d": {"a": 1}}) == "d={'a': 1}!"


class TestRecursion:
    def test_nested_dict(self):
        result = render({"kind": "{k}", "meta": {"n": "{n}"}}, {"k": "job", "n": 3})
        assert result == {"kind": "job", "meta": {"n": 3}}

    def test_nested_list(self):
        assert render(["{a}", "x-{a}"], {"a": 1}) == [1, "x-1"]


class TestMissingKeys:
    def test_missing_whole_placeholder_raises_wfact_001(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            render("{nope}", {})
        assert exc_info.value.code == "VAL-WFACT-001"

    def test_missing_mixed_key_raises_wfact_002(self):
        with pytest.raises(AudiaGenticError) as exc_info:
            render("x-{nope}", {})
        assert exc_info.value.code == "VAL-WFACT-002"

    def test_dotted_key_is_not_a_simple_placeholder(self):
        # \w+ does not match dots: "{a.b}" is NOT a whole placeholder; it
        # falls through to str.format, which treats it as attribute access.
        with pytest.raises(Exception):
            render("{a.b}", {"a": {"b": 1}})  # dict has no attribute 'b'


class TestPassthrough:
    def test_none_input(self):
        assert render(None, {}) is None

    def test_non_string_scalars_unchanged(self):
        assert render(5, {}) == 5
        assert render(2.5, {}) == 2.5
        assert render(True, {}) is True
