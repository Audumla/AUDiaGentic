"""Current keyword CLI boundary and retained serve shutdown lifecycle tests."""
import pytest

from audiagentic.commands import gateway


@pytest.mark.parametrize("command", ["drain", "resume", "stop", "recover"])
def test_retired_lifecycle_routes_are_rejected(command, capsys):
    assert gateway.dispatch_keyword([command]) == 2
    assert "gateway help" in capsys.readouterr().err
    assert not hasattr(gateway, f"cmd_gateway_{command}")


def test_gateway_exports_current_routes_only():
    assert gateway.__all__ == ["cmd_gateway", "dispatch_keyword"]


class TestServeSignals:
    def test_shutdown_signal_handler_calls_lifecycle_request_stop_forced(self) -> None:
        """SH10 Slice B: an OS shutdown signal goes straight to a forced stop
        -- no interactive way to "drain first" in response to SIGTERM."""
        from audiagentic.commands.gateway import _install_shutdown_signals

        class _FakeLifecycle:
            def __init__(self) -> None:
                self.calls: list[dict] = []

            def request_stop(self, *, force: bool = False) -> dict:
                self.calls.append({"force": force})
                return {"stopping": True, "forced": force}

        class _FakeHost:
            def __init__(self) -> None:
                self.lifecycle = _FakeLifecycle()
                self.shutdown_calls = 0

            def shutdown(self) -> None:
                self.shutdown_calls += 1

        host = _FakeHost()
        state = _install_shutdown_signals(host)

        import signal as signal_module
        handler = signal_module.getsignal(signal_module.SIGTERM)
        handler(signal_module.SIGTERM, None)

        assert host.lifecycle.calls == [{"force": True}]
        assert host.shutdown_calls == 0
        assert state.forced_fallback is False

        signal_module.signal(signal_module.SIGTERM, signal_module.SIG_DFL)

    def test_shutdown_signal_handler_falls_back_to_raw_shutdown_on_error(self) -> None:
        """If the lifecycle-mediated stop itself fails, fall back to a raw
        server shutdown so the process still exits rather than hanging --
        and record that the fallback path was taken."""
        from audiagentic.commands.gateway import _install_shutdown_signals

        class _FailingLifecycle:
            def request_stop(self, *, force: bool = False) -> dict:
                raise RuntimeError("lifecycle store unavailable")

        class _FakeHost:
            def __init__(self) -> None:
                self.lifecycle = _FailingLifecycle()
                self.shutdown_calls = 0

            def shutdown(self) -> None:
                self.shutdown_calls += 1

        host = _FakeHost()
        state = _install_shutdown_signals(host)

        import signal as signal_module
        handler = signal_module.getsignal(signal_module.SIGTERM)
        handler(signal_module.SIGTERM, None)

        assert host.shutdown_calls == 1
        assert state.forced_fallback is True

        signal_module.signal(signal_module.SIGTERM, signal_module.SIG_DFL)

    def test_shutdown_signal_handler_uses_raw_shutdown_when_no_lifecycle(self) -> None:
        """Embedded/no-lifecycle hosts (idle_grace<=0) still exit cleanly on
        a shutdown signal, via a direct server shutdown."""
        from audiagentic.commands.gateway import _install_shutdown_signals

        class _FakeHost:
            def __init__(self) -> None:
                self.lifecycle = None
                self.shutdown_calls = 0

            def shutdown(self) -> None:
                self.shutdown_calls += 1

        host = _FakeHost()
        state = _install_shutdown_signals(host)

        import signal as signal_module
        handler = signal_module.getsignal(signal_module.SIGTERM)
        handler(signal_module.SIGTERM, None)

        assert host.shutdown_calls == 1
        assert state.forced_fallback is False

        signal_module.signal(signal_module.SIGTERM, signal_module.SIG_DFL)

    def test_serve_help_is_current_pure_keyword_route(self, capsys):
        assert gateway.dispatch_keyword(["serve", "help"]) == 0
        assert "serve config FILE" in capsys.readouterr().out
