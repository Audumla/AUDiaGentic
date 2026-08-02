"""Smoke test: launch Chrome, navigate to ChatGPT, take a screenshot.

Human verifies:
  - Chrome window opens (or existing session reused)
  - chat.openai.com loads
  - screenshot is saved at /tmp/gpt-auto-smoke.png

    python tests/gpt_auto/test_launch.py
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

from audiagentic.components.providers.adapters.gpt_auto.playwright_client import (
    PlaywrightClient,
)


async def main() -> None:
    client = PlaywrightClient(
        target_url="https://chat.openai.com",
    )

    try:
        print("→ Launching Chrome …")
        await client.start()
        print(f"  URL: {await client.page.url if client.page else 'N/A'}")

        # Give the page a moment to fully render
        import asyncio as aio
        await aio.sleep(2)

        pg = client.page
        if pg is not None:
            title = await pg.title()
            print(f"  Title: {title}")

        print("→ Taking screenshot …")
        await client.screenshot(path="/tmp/gpt-auto-smoke.png")
        print("  Saved to /tmp/gpt-auto-smoke.png — open it and verify ChatGPT is loaded")

    finally:
        print("→ Closing browser …")
        await client.stop()

if __name__ == "__main__":
    asyncio.run(main())
