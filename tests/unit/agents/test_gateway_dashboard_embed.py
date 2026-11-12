from __future__ import annotations

import re

from audiagentic.components.agents.gateway.service.dashboard import (
    EMBED_ASSETS,
    render_dashboard_html,
    render_embed_asset,
    render_embed_html,
)


def test_embed_page_has_no_inline_code_and_only_relative_urls() -> None:
    page = render_embed_html("dark").decode()
    assert "<script>" not in page and "<style>" not in page
    assert 'data-embed="1"' in page and 'data-theme="dark"' in page
    for url in re.findall(r'(?:src|href)="([^"]+)"', page):
        assert not url.startswith(("/", "http")), url
    for name in EMBED_ASSETS:
        assert f"dashboard/static/{name}" in page


def test_embed_never_carries_the_action_token() -> None:
    full = render_dashboard_html("/dashboard/snapshot", focus_token="SECRET-ACTION-TOKEN").decode()
    assert "SECRET-ACTION-TOKEN" in full  # the normal page still works as before
    page = render_embed_html().decode()
    assets = b"".join(render_embed_asset(name)[1] for name in EMBED_ASSETS).decode()
    assert "SECRET" not in page + assets


def test_embed_assets_are_read_only_and_post_height() -> None:
    css = render_embed_asset("embed.css")[1].decode()
    assert ".action-button" in css and "display:none" in css
    js = render_embed_asset("embed.js")[1].decode()
    assert "agent-gateway-embed" in js and "postMessage" in js
    script = render_embed_asset("dashboard.js")[1].decode()
    assert "localStorage." not in script.replace("window.localStorage", "")
    assert 'new URL("dashboard/snapshot"' in script
    assert render_embed_asset("../secret") is None
