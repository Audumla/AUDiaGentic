"""Dashboard cancellation uses the canonical API and unique project ownership."""
from pathlib import Path
from unittest.mock import Mock

import pytest

from audiagentic.components.agents.gateway.service.application import GatewayServiceApplication
from audiagentic.components.agents.gateway.service.dashboard import render_dashboard_html
from audiagentic.foundation.contracts.errors import AudiaGenticError


@pytest.mark.parametrize("roots", [[], [Path("one"), Path("two")], [Path("one")]])
def test_cancel_requires_unique_request_owner(roots):
    application = object.__new__(GatewayServiceApplication)
    application._application = Mock()
    application._dashboard_request_projects = Mock(return_value=roots)
    if len(roots) != 1:
        with pytest.raises(AudiaGenticError, match="ambiguous"):
            application.cancel_dashboard_request("req_test")
        application._application.cancel_execution_request.assert_not_called()
    else:
        result = application.cancel_dashboard_request("req_test")
        application._application.cancel_execution_request.assert_called_once_with(roots[0], "req_test")
        assert result["outcome"] == "cancellation-requested"


def test_cancel_icon_is_active_only_and_accessible():
    html = render_dashboard_html("/dashboard/snapshot").decode()
    assert "function cancelControl(r) { return ACTIVE_REQUEST_STATES.has(r.state)?" in html
    assert 'aria-label="Cancel request"' in html
    assert "${cancelControl(r)}" in html
    assert "Cancellation requested for " in html
    assert 'id="request-action-feedback" role="status"' in html
