from concurrent.futures import ThreadPoolExecutor

from audiagentic.components.agents.gateway.service.client_icons import assign_client_icon, read_client_icon
from audiagentic.components.agents.gateway.service.dashboard import _request_row, render_dashboard_html


def test_cycle_and_stable_assignment(tmp_path):
    assert [assign_client_icon(tmp_path, f"client-{i}") for i in range(26)] == list(range(24)) + [0, 1]
    assert assign_client_icon(tmp_path, "client-4") == 4
    assert "client-4" not in (tmp_path / "client-icons.json").read_text()


def test_concurrent_assignment_is_serialized(tmp_path):
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert set(pool.map(lambda _: assign_client_icon(tmp_path, "same"), range(12))) == {0}
    assert assign_client_icon(tmp_path, "next") == 1


def test_assets_and_invalid_identifiers():
    for i in range(24):
        assert read_client_icon(str(i)).startswith(b"\x89PNG\r\n\x1a\n")
    for value in ["-1", "24", "../record.json", "", "1.0"]:
        assert read_client_icon(value) == b""


def test_dashboard_preserves_zero_icon_and_renders_before_id():
    assert _request_row({"request-id": "req_test", "client-icon": 0})["client-icon"] == 0
    html = render_dashboard_html("/custom/snapshot").decode()
    assert '${clientIcon(r)}<code class="request-id">' in html
    assert "new URL('client-icon',endpoint)" in html
