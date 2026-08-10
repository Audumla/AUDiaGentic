"""Test managed browser launch via BrowserManager."""

import asyncio
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from audiagentic.foundation.system.browser_manager import BrowserConfig, BrowserManager


async def main():
    port = 9231
    bm = BrowserManager(config=BrowserConfig(port=port))
    print(f"Starting managed browser on port {port}...")

    try:
        cdp_url = await bm.start()
        print(f"OK! CDP URL: {cdp_url}")

        # Verify CDP responds
        resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=3)
        data = json.loads(resp.read().decode())
        print(f"Browser: {data.get('Browser')}")

        tabs = json.loads(
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=3).read().decode()
        )
        print(f"Tabs: {len(tabs)}")

    except RuntimeError as e:
        print(f"Failed: {e}")
    finally:
        await bm.stop()
        print("Stopped.")


asyncio.run(main())
