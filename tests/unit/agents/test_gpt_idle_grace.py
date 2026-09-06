from types import SimpleNamespace

import pytest

from audiagentic.components.agents.gateway.session.idle_grace import gpt_idle_grace
from audiagentic.components.agents.gateway.session.sessions import _SessionHandle


@pytest.mark.parametrize("params,expected", [({}, 1800), ({"session-idle-timeout-seconds": 0}, 1800), ({"session-idle-timeout-seconds": 120}, 120)])
def test_false_keep_alive_has_finite_profile_driven_grace(params, expected):
    assert gpt_idle_grace(params) == expected


@pytest.mark.parametrize("value", [-1, True, "120", float("inf"), float("nan")])
def test_bad_policy_rejected(value):
    with pytest.raises(Exception, match="finite non-negative"):
        gpt_idle_grace({"session-idle-timeout-seconds": value})


def test_grace_can_replace_unlimited_live_idle_bound_without_turn_deadline():
    handle = SimpleNamespace(idle_timeout_seconds=0, max_lifetime_seconds=0)
    _SessionHandle.update_bounds(handle, idle_timeout_seconds=120, replace_idle_timeout=True)
    assert handle.idle_timeout_seconds == 120
    assert handle.max_lifetime_seconds == 0
