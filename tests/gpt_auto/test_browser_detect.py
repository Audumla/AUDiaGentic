"""Smoke test: browser detection.

Runs fast — no browser needed, just checks that we can find an installed
Chromium binary on this machine.

    python tests/gpt_auto/test_browser_detect.py
"""

from audiagentic.components.providers.adapters.gpt_auto.playwright_client import (
    detect_chromium_browser,
)


def main() -> None:
    browser = detect_chromium_browser()
    if browser is None:
        print("FAIL — no Chromium browser detected")
        return

    print(f"OK — {browser.name} found at:\n  {browser.path}")
    print(f"    exists: {browser.path.exists()}")
    print(f"    executable: {browser.path.stat().st_mode & 0o111 != 0}")

if __name__ == "__main__":
    main()
