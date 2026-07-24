"""PI04: native Pi durable config must survive isolated-job execution untouched."""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.agents_gateway_worker import _replacement_environment


def test_replacement_environment_never_writes_into_native_pi_home(
    tmp_path: Path, monkeypatch
) -> None:
    native_home = tmp_path / "native-home"
    native_pi_dir = native_home / ".pi" / "agent"
    native_pi_dir.mkdir(parents=True)
    native_mcp_config = native_home / ".pi" / "mcp.json"
    native_mcp_config.write_text('{"mcpServers": {"native": {}}}', encoding="utf-8")
    native_models = native_pi_dir / "models.json"
    native_models.write_text('{"models": ["native-model"]}', encoding="utf-8")
    before = native_models.read_bytes()
    before_mcp = native_mcp_config.read_bytes()

    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    monkeypatch.setattr(Path, "home", lambda: native_home)

    private_home = tmp_path / "worker-private-home"
    private_home.mkdir()
    environment = _replacement_environment("test-profile", private_home)

    # Job config must be scoped to the private worker home, never the caller's
    # durable ~/.pi.
    assert environment["HOME"] == str(private_home)
    assert environment["PI_CODING_AGENT_DIR"] == str(private_home / ".pi" / "agent")
    assert environment["PI_CODING_AGENT_DIR"] != str(native_pi_dir)

    # The caller's native durable config is read-only source material — it
    # must be byte-for-byte unchanged after preparing the isolated job env.
    assert native_models.read_bytes() == before
    assert native_mcp_config.read_bytes() == before_mcp

    # The only artifact copied from native state is models.json, and only
    # into the private worker home — never back into the native tree.
    copied_models = private_home / ".pi" / "agent" / "models.json"
    assert copied_models.is_file()
    assert copied_models.read_bytes() == before
