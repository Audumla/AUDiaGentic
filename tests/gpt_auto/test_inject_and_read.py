"""Smoke test: inject a prompt and read the response.

Human verifies:
  - Chrome opens with ChatGPT loaded
  - The prompt text appears in the input box
  - Enter is pressed and the prompt is sent
  - A response appears in the ChatGPT page
  - The printed output matches what's on screen

    python tests/gpt_auto/test_inject_and_read.py
"""

from __future__ import annotations

import asyncio
import logging

from audiagentic.components.providers.adapters.gpt_auto.dom_reader import (
    wait_for_response,
)
from audiagentic.components.providers.adapters.gpt_auto.playwright_client import (
    PlaywrightClient,
)
from audiagentic.components.providers.adapters.gpt_auto.prompt_injector import (
    inject_prompt,
    wait_for_chatgpt_ready,
)

logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

TEST_PROMPT = "Say 'hello from gpt-auto smoke test' and nothing else."

async def main() -> None:
    client = PlaywrightClient(
        target_url="https://chat.openai.com",
    )

    try:
        print("→ Launching Chrome …")
        await client.start()
        print("  Navigated to ChatGPT")

        # Wait for the user to log in if needed
        print("→ Waiting for ChatGPT to be ready (or you to log in) …")
        ready = await wait_for_chatgpt_ready(client, timeout=30.0)
        if not ready:
            await client.screenshot(path="/tmp/gpt-auto-not-ready.png")
            print("FAIL — ChatGPT not ready after 30s. Screenshot saved.")
            return

        print("→ ChatGPT is ready")

        # Inject the test prompt
        print(f"→ Injecting prompt: {TEST_PROMPT!r}")
        await inject_prompt(client, TEST_PROMPT)
        print("  Prompt submitted")

        # Wait for response
        print("→ Waiting for response …")
        response = await wait_for_response(
            client,
            timeout=60.0,
            interval=2.0,
            on_chunk=lambda t: print(f"  [chunk] {t[-80:] if len(t) > 80 else t}"),
        )

        if response is None:
            print("FAIL — no response received")
            await client.screenshot(path="/tmp/gpt-auto-no-response.png")
            return

        print(f"\n→ Response ({len(response)} chars):\n{'-'*60}")
        print(response)
        print("-" * 60)

        # Verify the expected phrase is in the response
        if "hello from gpt-auto" in response.lower():
            print("\nPASS — expected phrase found in response")
        else:
            print("\nWARN — expected phrase NOT in response (may still be OK)")

        # Save final state for human review
        await client.screenshot(path="/tmp/gpt-auto-done.png")
        print("  Final screenshot saved to /tmp/gpt-auto-done.png")

    finally:
        print("→ Closing browser …")
        await client.stop()

if __name__ == "__main__":
    asyncio.run(main())
