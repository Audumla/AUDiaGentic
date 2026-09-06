"""Client-scoped default selection must not overwrite explicit chat choices."""
from unittest.mock import patch

from audiagentic.components.agents.gateway.session import client_defaults as defaults
from audiagentic.foundation.contracts.errors import AudiaGenticError


def selection(root, **overrides):
    args = dict(service_root=str(root / "service"), client_id="client-a",
                agent_id="gpt-agent", provider_id="gpt-auto", session_id=None,
                provider_chat_url=None, new_session=False)
    args.update(overrides)
    return defaults.select(root, **args)


def test_first_session_becomes_default_and_explicit_does_not_replace(tmp_path):
    with selection(tmp_path, session_id="ses_first") as chosen:
        chosen.commit({"session-id": "ses_first"})
    with selection(tmp_path, new_session=True) as chosen:
        chosen.commit({"session-id": "ses_separate"})
    with selection(tmp_path, session_id="ses_explicit") as chosen:
        chosen.commit({"session-id": "ses_explicit"})
    with patch("audiagentic.components.agents.gateway.session.sessions_store.read_session_record", return_value={}):
        with selection(tmp_path) as chosen:
            assert chosen.session_id == "ses_first"
            assert chosen.automatic


def test_scope_isolates_client_project_and_agent(tmp_path):
    original = defaults.scope_key("a", tmp_path, "gpt")
    assert original != defaults.scope_key("b", tmp_path, "gpt")
    assert original != defaults.scope_key("a", tmp_path / "other", "gpt")
    assert original != defaults.scope_key("a", tmp_path, "other")


def test_non_gpt_does_not_bind(tmp_path):
    with selection(tmp_path, provider_id="codex") as chosen:
        assert chosen.identity is None
        chosen.commit({"session-id": "ses_codex"})
    assert not (tmp_path / "service").exists()


def test_proven_unsent_failure_never_replaces_default(tmp_path):
    error = AudiaGenticError(code="EXT-GPTAUTO-003", kind="providers", message="timeout", details={"failure-reason":"composer-operation-timeout","submission-ambiguous":False})
    with selection(tmp_path) as chosen:
        chosen.commit({"session-id":"ses_original"})
        path = chosen.path
    with patch.object(defaults, "_attach") as attach:
        assert defaults.replace_failed_default(tmp_path, {}, error, recover_url=False) is None
        attach.assert_not_called()
    assert defaults._read(path)["session-id"] == "ses_original"


def test_missing_session_retains_chat_recovery_reference(tmp_path):
    url = "https://chatgpt.com/g/g-p-example/c/conversation"
    with selection(tmp_path, provider_chat_url=url) as chosen:
        chosen.commit({"session-id": "ses_deleted"})
    error = AudiaGenticError(code="RES-AGW-003", kind="agents", message="missing")
    with patch("audiagentic.components.agents.gateway.session.sessions_store.read_session_record", side_effect=error):
        with selection(tmp_path) as chosen:
            assert chosen.session_id is None
            assert chosen.provider_chat_url == url
            assert chosen.warnings[0]["code"] == "RES-AGW-003"
            assert url not in str(chosen.warnings)


def test_first_explicit_new_session_establishes_default(tmp_path):
    with selection(tmp_path, new_session=True) as chosen:
        chosen.commit({"session-id": "ses_first"})
        assert defaults._read(chosen.path)["session-id"] == "ses_first"


def test_preparation_guard_shared_only_while_in_use():
    record = {"client-default-session": {"key": "a" * 64}}
    guard = defaults.preparation_guard(record)
    assert defaults.preparation_guard(record) is guard


def test_late_failure_does_not_overwrite_replacement(tmp_path):
    with selection(tmp_path) as chosen:
        chosen.commit({"session-id": "ses_replacement"})
        identity = chosen.identity
        path = chosen.path
    record = {"client-default-session": identity, "dispatch-service-root": str(tmp_path / "service"),
              "session-id": "ses_old", "request-id": "req_test", "dispatch-owner-epoch": "owner", "worker-id": "worker", "attempt-epoch": 1, "execution-profile-id": "gpt", "resolved-provider-id": "gpt-auto"}
    with patch.object(defaults, "_attach", return_value={}) as attach, patch("audiagentic.components.agents.gateway.store.append_owned_attempt") as evidence:
        defaults.replace_failed_default(tmp_path, record, RuntimeError("private"), recover_url=False, attach_request=False)
        assert str(evidence.call_args.kwargs["error"]) == "private"
    assert defaults._read(path)["session-id"] == "ses_replacement"
    assert attach.call_args.args[2] == "ses_old"
    assert "private" not in str(attach.call_args)
