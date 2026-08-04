"""SH03 conformance tests for the public in-process gateway client."""
from __future__ import annotations

from pathlib import Path

from audiagentic.components.agents.gateway.client import InProcessGatewayClient


class _ApplicationStub:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def submit_execution_request(self, project_root: Path, **kwargs: object) -> dict[str, object]:
        self.calls.append(("submit", (project_root,), kwargs))
        return {"state": "queued"}


def test_in_process_client_delegates_to_its_application(tmp_path: Path) -> None:
    application = _ApplicationStub()
    client = InProcessGatewayClient(application)  # type: ignore[arg-type]

    assert client.submit_execution_request(tmp_path, prompt_body="hello") == {"state": "queued"}
    assert application.calls == [("submit", (tmp_path,), {"prompt_body": "hello"})]


def test_inbound_adapters_depend_on_public_client_not_core_api() -> None:
    agents_dir = Path(__file__).parents[3] / "src" / "audiagentic" / "components" / "agents"
    for rel in ("mcp/gateway_mcp.py", "gateway/events.py"):
        source = (agents_dir / rel).read_text(encoding="utf-8")
        assert "gateway.api import" not in source
        assert "gateway.client import get_gateway_client" in source
