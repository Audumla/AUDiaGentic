"""RV1261: a multi-address refusal reaches the host as one concrete, retryable error."""
from __future__ import annotations

import sys

import pytest

from audiagentic.components.agents.gateway.node import transport

pytestmark = pytest.mark.skipif(transport._EXCEPTION_GROUP is None, reason="needs ExceptionGroup (Python 3.11+)")


def _refused(address: str) -> ConnectionRefusedError:
    return ConnectionRefusedError(111, f"refused {address}")


def test_all_refusals_give_one_retryable_connection_error():
    group = ExceptionGroup("Multiple exceptions", [_refused("::1"), _refused("127.0.0.1")])
    chosen = transport._representative_connect_error(group)
    assert isinstance(chosen, ConnectionRefusedError) and chosen.errno == 111  # the host's errno retry rule applies


def test_an_unusual_address_failure_wins_over_a_refusal_and_stays_fail_closed():
    group = ExceptionGroup("Multiple exceptions", [_refused("::1"), PermissionError(13, "denied")])
    assert isinstance(transport._representative_connect_error(group), PermissionError)


def test_nested_groups_are_flattened():
    inner = ExceptionGroup("inner", [_refused("::1")])
    outer = ExceptionGroup("outer", [inner, _refused("127.0.0.1")])
    assert isinstance(transport._representative_connect_error(outer), ConnectionRefusedError)


def test_the_all_errors_option_is_requested_only_where_supported():
    assert transport._CONNECT_ERRORS == ({"all_errors": True} if sys.version_info >= (3, 12) else {})
