"""Unit coverage for config-driven, system-installed harness resolution."""
from __future__ import annotations

from audiagentic.runtime.harness import resolution


def test_prefers_first_installed_in_order(monkeypatch) -> None:
    # pi present, opencode present -> pi wins (order given by caller/config).
    monkeypatch.setattr(
        resolution.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"pi", "opencode"} else None
    )
    resolved = resolution.resolve_launch_harness(["pi", "opencode"])
    assert resolved is not None
    assert resolved.harness_type == "pi"
    assert resolved.cli_path == "/usr/bin/pi"


def test_falls_back_when_preferred_absent(monkeypatch) -> None:
    # pi NOT installed -> falls back to opencode.
    monkeypatch.setattr(
        resolution.shutil, "which", lambda name: "/usr/bin/opencode" if name == "opencode" else None
    )
    resolved = resolution.resolve_launch_harness(["pi", "opencode"])
    assert resolved is not None
    assert resolved.harness_type == "opencode"


def test_returns_none_when_nothing_installed(monkeypatch) -> None:
    monkeypatch.setattr(resolution.shutil, "which", lambda name: None)
    assert resolution.resolve_launch_harness(["pi", "opencode"]) is None


def test_empty_order_resolves_none() -> None:
    assert resolution.resolve_launch_harness([]) is None


def test_order_is_honored_exactly(monkeypatch) -> None:
    monkeypatch.setattr(
        resolution.shutil, "which", lambda name: f"/usr/bin/{name}" if name in {"pi", "opencode"} else None
    )
    resolved = resolution.resolve_launch_harness(["opencode", "pi"])
    assert resolved is not None
    assert resolved.harness_type == "opencode"


def test_real_system_pi_is_discoverable() -> None:
    # No mock: resolution must resolve the system CLI, never the embedded copy.
    path = resolution.harness_cli_available("pi")
    assert path is None or "audiagentic" not in path.lower(), (
        f"harness resolution must resolve the system CLI (got {path!r})"
    )


def test_get_harness_type_is_config_order_driven(monkeypatch) -> None:
    from audiagentic.runtime import harness as facade

    # No pin, order [pi, opencode]; pi absent, opencode present -> opencode.
    monkeypatch.setattr(
        facade, "get_harness_type", facade.get_harness_type
    )  # ensure real impl
    monkeypatch.setattr(
        "audiagentic.foundation.config.load_layered_config",
        lambda **_kw: {"harness": {"order": ["pi", "opencode"]}},
    )
    monkeypatch.setattr(
        resolution.shutil, "which", lambda name: "/usr/bin/opencode" if name == "opencode" else None
    )
    assert facade.get_harness_type() == "opencode"


def test_get_harness_type_pin_overrides_order(monkeypatch) -> None:
    from audiagentic.runtime import harness as facade

    monkeypatch.setattr(
        "audiagentic.foundation.config.load_layered_config",
        lambda **_kw: {"harness": {"type": "pi", "order": ["opencode"]}},
    )
    # Even with nothing installed, the explicit pin wins.
    monkeypatch.setattr(resolution.shutil, "which", lambda name: None)
    assert facade.get_harness_type() == "pi"


def test_get_harness_type_falls_back_to_first_when_none_installed(monkeypatch) -> None:
    from audiagentic.runtime import harness as facade

    monkeypatch.setattr(
        "audiagentic.foundation.config.load_layered_config",
        lambda **_kw: {"harness": {"order": ["pi", "opencode"]}},
    )
    monkeypatch.setattr(resolution.shutil, "which", lambda name: None)
    # Nothing installed -> most-preferred configured harness, so config/dispatch
    # still target a valid harness module.
    assert facade.get_harness_type() == "pi"
