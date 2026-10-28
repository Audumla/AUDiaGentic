"""Settings merge is RFC 7396 JSON Merge Patch, with provenance."""
from __future__ import annotations

import pytest

from audiagentic.foundation.config.merge import Origin, merge_patch

# RFC 7396, Appendix A (example test cases), verbatim.
RFC_7396_APPENDIX_A = [
    ({"a": "b"}, {"a": "c"}, {"a": "c"}),
    ({"a": "b"}, {"b": "c"}, {"a": "b", "b": "c"}),
    ({"a": "b"}, {"a": None}, {}),
    ({"a": "b", "b": "c"}, {"a": None}, {"b": "c"}),
    ({"a": ["b"]}, {"a": "c"}, {"a": "c"}),
    ({"a": "c"}, {"a": ["b"]}, {"a": ["b"]}),
    ({"a": {"b": "c"}}, {"a": {"b": "d", "c": None}}, {"a": {"b": "d"}}),
    ({"a": [{"b": "c"}]}, {"a": [1]}, {"a": [1]}),
    (["a", "b"], ["c", "d"], ["c", "d"]),
    ({"a": "b"}, ["c"], ["c"]),
    ({"a": "foo"}, None, None),
    ({"a": "foo"}, "bar", "bar"),
    ({"e": None}, {"a": 1}, {"e": None, "a": 1}),
    ([1, 2], {"a": "b", "c": None}, {"a": "b"}),
    ({}, {"a": {"bb": {"ccc": None}}}, {"a": {"bb": {}}}),
]


@pytest.mark.parametrize(("target", "patch", "expected"), RFC_7396_APPENDIX_A)
def test_rfc_7396_appendix_a(target, patch, expected) -> None:
    assert merge_patch(target, patch, {}, lambda pointer: Origin("test")) == expected


def _origin(scope: str):
    return lambda pointer: Origin(scope, f"{scope}.yaml", 1, 1)


def test_provenance_tracks_winner_and_tombstones() -> None:
    origins: dict = {}
    value = merge_patch({}, {"a": {"x": 1, "y": [1, 2]}, "b": 1}, origins, _origin("vendor"))
    value = merge_patch(value, {"a": {"x": 2, "y": None}, "c": [3]}, origins, _origin("project"))

    assert value == {"a": {"x": 2}, "b": 1, "c": [3]}
    assert origins["/a/x"].scope == "project"
    assert origins["/b"].scope == "vendor"
    assert origins["/a/y"] == Origin("project", "project.yaml", 1, 1, deleted=True)
    assert "/a/y/0" not in origins  # descendants of a deleted value are gone
    assert origins["/c/0"].scope == "project"


def test_replacing_a_value_with_another_type_forgets_old_descendants() -> None:
    origins: dict = {}
    value = merge_patch({}, {"a": {"x": 1}}, origins, _origin("vendor"))
    value = merge_patch(value, {"a": [9]}, origins, _origin("user"))
    assert value == {"a": [9]}
    assert "/a/x" not in origins
    assert origins["/a/0"].scope == "user"


def test_later_scope_revives_deleted_value() -> None:
    origins: dict = {}
    value = merge_patch({}, {"a": 1}, origins, _origin("vendor"))
    value = merge_patch(value, {"a": None}, origins, _origin("user"))
    value = merge_patch(value, {"a": 2}, origins, _origin("project"))
    assert value == {"a": 2}
    assert origins["/a"] == Origin("project", "project.yaml", 1, 1)


def test_merge_does_not_mutate_inputs() -> None:
    target = {"a": {"b": [1]}}
    patch = {"a": {"c": 1}}
    merge_patch(target, patch, {}, _origin("x"))
    assert target == {"a": {"b": [1]}}
    assert patch == {"a": {"c": 1}}
