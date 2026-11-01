"""Client-scoped default selection must not overwrite explicit chat choices."""
from unittest.mock import patch

import pytest

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
    assert original != defaults.scope_key("a", tmp_path, "gpt", "other-surface")


def test_each_logical_client_has_an_independent_default(tmp_path):
    with selection(tmp_path, client_id="client-a") as chosen:
        chosen.commit({"session-id": "ses-a"})
    with selection(tmp_path, client_id="client-b") as chosen:
        assert chosen.session_id is None
        chosen.commit({"session-id": "ses-b"})

    with patch("audiagentic.components.agents.gateway.session.sessions_store.read_session_record", return_value={}):
        with selection(tmp_path, client_id="client-a") as chosen:
            assert chosen.session_id == "ses-a"
        with selection(tmp_path, client_id="client-b") as chosen:
            assert chosen.session_id == "ses-b"


def test_default_binding_rejects_cross_client_session_collision(tmp_path):
    with selection(tmp_path, client_id="client-a") as chosen:
        chosen.commit({"session-id": "ses-shared-by-mistake"})

    # Simulate a previously persisted collision.  The second client must not
    # continue using the first client's provider conversation.
    with selection(tmp_path, client_id="client-b") as chosen:
        chosen.commit({"session-id": "ses-shared-by-mistake"})

    with selection(tmp_path, client_id="client-b") as chosen:
        assert chosen.session_id is None
        assert chosen.provider_chat_url is None
        assert chosen.warnings[0]["code"] == "CON-AGW-123"


def test_legacy_default_binding_is_ignored_instead_of_adopted(tmp_path):
    path = tmp_path / "service" / "client-default-sessions" / (
        defaults.scope_key("client-a", tmp_path, "gpt-agent") + ".json"
    )
    path.parent.mkdir(parents=True)
    path.write_text('{"session-id":"ses-legacy","schema-generation":1}', encoding="utf-8")

    with selection(tmp_path, client_id="client-a") as chosen:
        assert chosen.session_id is None
        assert chosen.identity["schema-generation"] == 2


def test_non_gpt_does_not_bind(tmp_path):
    with selection(tmp_path, provider_id="codex") as chosen:
        assert chosen.identity is None
        chosen.commit({"session-id": "ses_codex"})
    assert not (tmp_path / "service").exists()


def test_proven_presubmit_failure_never_replaces_default(tmp_path):
    error = AudiaGenticError(code="EXT-GPTAUTO-004", kind="providers", message="timeout", details={
        "failure-stage": "readiness", "submission-state": "not_started",
        "submission-proven": False, "submission-ambiguous": False,
        "retryable-same-session": True,
    })
    assert defaults.structured_presubmit_failure(error)
    assert defaults.proven_same_session_presubmit_retryable_failure(error)
    with selection(tmp_path) as chosen:
        chosen.commit({"session-id":"ses_original"})
        path = chosen.path
    with patch.object(defaults, "_attach") as attach:
        assert defaults.replace_failed_default(tmp_path, {}, error, recover_url=False) is None
        attach.assert_not_called()
    assert defaults._read(path)["session-id"] == "ses_original"


def test_presubmit_retry_requires_explicit_same_session_proof():
    base = {
        "failure-stage": "readiness",
        "submission-state": "not_started",
        "submission-proven": False,
        "submission-ambiguous": False,
    }
    assert not defaults.proven_same_session_presubmit_retryable_failure(
        AudiaGenticError("EXT-GPTAUTO-004", "providers", "blocked", {**base, "retryable-same-session": False})
    )
    assert not defaults.structured_presubmit_failure(RuntimeError("not typed"))


def test_presubmit_cause_is_bounded_and_redacted():
    cause = RuntimeError("https://private.example/x C:\\example-home\\secret " + "x" * 500)
    value = defaults._bounded_cause_message(cause)
    assert len(value) <= 240
    assert "private.example" not in value
    assert "C:\\Users" not in value


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


def test_terminal_default_session_is_not_reused_and_retains_chat(tmp_path):
    url = "https://chatgpt.com/g/g-p-example/c/conversation"
    with selection(tmp_path, provider_chat_url=url) as chosen:
        chosen.commit({"session-id": "ses_terminal"})

    terminal = {
        "session-id": "ses_terminal",
        "state": "failed",
        "provider-metadata": {"chat-url": url},
    }
    with patch(
        "audiagentic.components.agents.gateway.session.sessions_store.read_session_record",
        return_value=terminal,
    ):
        with selection(tmp_path) as chosen:
            assert chosen.session_id is None
            assert chosen.provider_chat_url == url
            assert chosen.warnings[0]["code"] == "RES-AGW-003"


@pytest.mark.parametrize("state", ["failed", "closed", "expired", "unknown"])
def test_only_terminal_default_states_are_replaced(tmp_path, state):
    url = "https://chatgpt.com/g/g-p-example/c/conversation"
    with selection(tmp_path, provider_chat_url=url) as chosen:
        chosen.commit({"session-id": "ses_state"})
    session = {
        "session-id": "ses_state",
        "state": state,
        "provider-metadata": {"chat-url": url},
    }
    with patch(
        "audiagentic.components.agents.gateway.session.sessions_store.read_session_record",
        return_value=session,
    ):
        with selection(tmp_path) as chosen:
            assert chosen.session_id is None
            assert chosen.provider_chat_url == url


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


# --- SH33 acceptance evidence: concurrent first selections, restart durability, multi-process serialization ---

import json
import subprocess
import sys
import threading
from pathlib import Path


def test_concurrent_first_selections_establish_one_binding_and_everyone_reuses_it(tmp_path):
    """Many first calls race for a blank selection: exactly one creates the default, the rest reuse it."""
    barrier = threading.Barrier(8)
    outcomes: list[tuple[str, bool]] = []
    guard = threading.Lock()

    def first_call(index: int) -> None:
        barrier.wait()
        with selection(tmp_path) as chosen:
            created = chosen.session_id is None
            if created:
                chosen.session_id = f"ses_created_by_{index}"
                chosen.commit({"session-id": chosen.session_id})
            with guard:
                outcomes.append((chosen.session_id, created))

    threads = [threading.Thread(target=first_call, args=(index,)) for index in range(8)]
    # The default's session must look present (the design replaces a missing one by intent).
    with patch("audiagentic.components.agents.gateway.session.sessions_store.read_session_record", return_value={}):
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
    assert len(outcomes) == 8
    assert sum(1 for _, created in outcomes if created) == 1  # one atomic establishment
    assert len({session_id for session_id, _ in outcomes}) == 1  # and everyone resolved to it
    with patch("audiagentic.components.agents.gateway.session.sessions_store.read_session_record", return_value={}):
        with selection(tmp_path) as chosen:
            assert chosen.session_id == outcomes[0][0] and chosen.automatic


def test_an_explicit_override_during_a_race_never_changes_the_default(tmp_path):
    with selection(tmp_path, session_id="ses_default") as chosen:
        chosen.commit({"session-id": "ses_default"})
    barrier = threading.Barrier(6)

    def override(index: int) -> None:
        barrier.wait()
        with selection(tmp_path, session_id=f"ses_explicit_{index}") as chosen:
            chosen.commit({"session-id": f"ses_explicit_{index}"})

    threads = [threading.Thread(target=override, args=(index,)) for index in range(6)]
    with patch("audiagentic.components.agents.gateway.session.sessions_store.read_session_record", return_value={}):
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
        with selection(tmp_path) as chosen:
            assert chosen.session_id == "ses_default"


def test_the_default_survives_a_process_restart(tmp_path):
    """A brand-new interpreter reads the durable binding and reuses the same session (client defaults need not
    survive the client process, but the gateway-owned binding must survive the gateway process)."""
    with selection(tmp_path, session_id="ses_before_restart") as chosen:
        chosen.commit({"session-id": "ses_before_restart"})
    script = (
        "import json,sys\n"
        "from pathlib import Path\n"
        "from unittest.mock import patch\n"
        "from audiagentic.components.agents.gateway.session import client_defaults as d\n"
        "root=Path(sys.argv[1])\n"
        "with patch('audiagentic.components.agents.gateway.session.sessions_store.read_session_record', return_value={}):\n"
        "    with d.select(root, service_root=str(root/'service'), client_id='client-a', agent_id='gpt-agent',\n"
        "                  provider_id='gpt-auto', session_id=None, provider_chat_url=None, new_session=False) as s:\n"
        "        print(json.dumps([s.session_id, s.automatic]))\n"
    )
    env = {**__import__("os").environ, "PYTHONPATH": str(Path(defaults.__file__).resolve().parents[5])}
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True,
                            env=env, timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == ["ses_before_restart", True]


def test_two_processes_selecting_at_once_still_establish_one_binding(tmp_path):
    script = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from unittest.mock import patch\n"
        "from audiagentic.components.agents.gateway.session import client_defaults as d\n"
        "root=Path(sys.argv[1]); name=sys.argv[2]\n"
        "patch('audiagentic.components.agents.gateway.session.sessions_store.read_session_record', return_value={}).start()\n"
        "with d.select(root, service_root=str(root/'service'), client_id='client-a', agent_id='gpt-agent',\n"
        "              provider_id='gpt-auto', session_id=None, provider_chat_url=None, new_session=False) as s:\n"
        "    if s.session_id is None:\n"
        "        time.sleep(0.3)\n"
        "        s.commit({'session-id': 'ses_by_'+name}); print('created')\n"
        "    else:\n"
        "        print('reused:'+s.session_id)\n"
    )
    env = {**__import__("os").environ, "PYTHONPATH": str(Path(defaults.__file__).resolve().parents[5])}
    procs = [subprocess.Popen([sys.executable, "-c", script, str(tmp_path), name], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True, env=env) for name in ("a", "b")]
    results = [process.communicate(timeout=90) for process in procs]
    assert all(process.returncode == 0 for process in procs), [r[1] for r in results]
    lines = sorted(out.strip().splitlines()[-1] for out, _ in results)
    created = [line for line in lines if line == "created"]
    reused = [line for line in lines if line.startswith("reused:")]
    assert len(created) == 1 and len(reused) == 1  # the second waited for the first and reused its session
    assert reused[0].split(":", 1)[1] in {"ses_by_a", "ses_by_b"}
