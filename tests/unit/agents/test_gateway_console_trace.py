from __future__ import annotations

from io import StringIO

from audiagentic.components.agents.gateway.session.console_trace import GatewayConsoleTrace


def test_summary_trace_contains_launch_progress_and_terminal_metadata(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE", "summary")
    stream = StringIO()
    trace = GatewayConsoleTrace(stream=stream, clock=lambda: 12.0)

    trace.session_opened(
        session_id="ses_1",
        provider_id="codex",
        model_id="gpt-5.6-luna[high]",
        execution_profile_id="codex-luna-high",
        surface_id="codex-acp",
        child_pid=123,
    )
    started = trace.turn_started(request_id="req_1", session_id="ses_1", prompt="secret prompt")
    trace.progress(
        request_id="req_1",
        session_id="ses_1",
        kind="thinking",
        sequence=2,
        started=started,
        force=True,
    )
    trace.finished(
        request_id="req_1",
        session_id="ses_1",
        outcome="success",
        output="secret output",
        started=started,
    )

    rendered = stream.getvalue()
    assert "START" in rendered
    assert "provider=codex" in rendered
    assert "model=gpt-5.6-luna[high]" in rendered
    assert "harness=codex-acp" in rendered
    assert "PROGRESS" in rendered and "activity=thinking" in rendered
    assert "COMPLETE" in rendered and "output_chars=13" in rendered
    assert "secret prompt" not in rendered
    assert "secret output" not in rendered


def test_full_trace_includes_bounded_prompt_and_output(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE", "full")
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE_MAX_CHARS", "256")
    stream = StringIO()
    trace = GatewayConsoleTrace(stream=stream, clock=lambda: 1.0)
    started = trace.turn_started(request_id="req_1", session_id="ses_1", prompt="p" * 300)
    trace.finished(
        request_id="req_1",
        session_id="ses_1",
        outcome="failed",
        output="o" * 300,
        error_code="EXT-ACP-TOOL-001",
        started=started,
    )

    rendered = stream.getvalue()
    assert "prompt=" + ("p" * 256) in rendered
    assert "output=" + ("o" * 256) in rendered
    assert "error_code=EXT-ACP-TOOL-001" in rendered
    assert "..." in rendered


def test_trace_can_be_disabled(monkeypatch):
    monkeypatch.setenv("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE", "off")
    stream = StringIO()
    trace = GatewayConsoleTrace(stream=stream)
    trace.session_opened(
        session_id="ses_1",
        provider_id="codex",
        model_id=None,
        execution_profile_id="profile",
        surface_id=None,
        child_pid=None,
    )
    assert stream.getvalue() == ""


def test_default_trace_sink_is_shared_gateway_log(monkeypatch, tmp_path):
    import audiagentic.components.agents.gateway.session.console_trace as module

    monkeypatch.delenv("AUDIAGENTIC_GATEWAY_CONSOLE_TRACE_FILE", raising=False)
    monkeypatch.setattr(module, "global_log_dir", lambda component: tmp_path / component)
    trace = GatewayConsoleTrace()
    trace.session_opened(
        session_id="ses_1",
        provider_id="codex",
        model_id="gpt-5.6-luna[high]",
        execution_profile_id="codex-luna-high",
        surface_id="codex-acp",
        child_pid=123,
    )

    rendered = (tmp_path / "gateway" / "console-trace.log").read_text(encoding="utf-8")
    assert "START" in rendered
    assert "session=ses_1" in rendered
