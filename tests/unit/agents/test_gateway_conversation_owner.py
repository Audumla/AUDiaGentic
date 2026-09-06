from unittest.mock import patch
import pytest
from audiagentic.components.agents.gateway.session.conversation_owner import resolve_conversation_owner
from audiagentic.foundation.contracts.errors import AudiaGenticError

URL = "https://chatgpt.com/g/g-p-project-slug/c/conversation"

def owner(session="ses_existing", state="active"):
    return {"session-id": session, "state": state, "binding": {"provider-id": "gpt-auto", "provider-session-ref": "conversation"}}

@pytest.mark.parametrize("explicit", [None, "ses_existing"])
def test_reuses_existing_queue(tmp_path, explicit):
    with patch("audiagentic.components.agents.gateway.session.sessions_store.list_session_records", return_value=[owner()]):
        assert resolve_conversation_owner(tmp_path, URL, explicit) == "ses_existing"

def test_prefers_live_successor(tmp_path):
    with patch("audiagentic.components.agents.gateway.session.sessions_store.list_session_records", return_value=[owner("ses_old", "closed"), owner()]):
        assert resolve_conversation_owner(tmp_path, URL, None) == "ses_existing"

def test_conflicting_explicit_session_rejected(tmp_path):
    with patch("audiagentic.components.agents.gateway.session.sessions_store.list_session_records", return_value=[owner()]):
        with pytest.raises(AudiaGenticError):
            resolve_conversation_owner(tmp_path, URL, "ses_other")

def test_unowned_url_allows_new_session(tmp_path):
    with patch("audiagentic.components.agents.gateway.session.sessions_store.list_session_records", return_value=[]):
        assert resolve_conversation_owner(tmp_path, URL, None) is None
