"""Quick smoke test: managed browser launch + CDP on isolated port."""

# type: ignore[import]
import asyncio
import json
import sys
import urllib.request

sys.path.insert(0, "src")

from audiagentic.foundation.system.browser_manager import (  # noqa: E402
    BrowserConfig,
    BrowserManager,
)


async def main() -> None:  # pragma: no cover
    """Launch managed browser on port 9223 and verify CDP."""
    bm = BrowserManager(config=BrowserConfig(port=9223))

    print("Starting managed browser on port 9223...")
    cdp_url = await bm.start()
    print(f"OK - Started: {cdp_url}")
    print(f"  PID: {bm._evidence.pid if bm._evidence else 'N/A'}")
    print(f"  Browser: {bm.browser_path}")

    # Verify CDP endpoint
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:9223/json/version", timeout=5)
        data = json.loads(resp.read().decode())
        print(f"  WebSocket: {data.get('webSocketDebuggerUrl')}")
        print(f"  Browser: {data.get('Browser')}")

        # List tabs (should be empty - clean profile)
        resp2 = urllib.request.urlopen("http://127.0.0.1:9223/json", timeout=5)
        tabs = json.loads(resp2.read().decode())
        print(f"  Tabs: {len(tabs)}")
    except Exception as exc:
        print(f"  CDP check: {exc}")

    # Stop it
    print("\nStopping managed browser...")
    await bm.stop()
    print("OK - Stopped")


asyncio.run(main())
