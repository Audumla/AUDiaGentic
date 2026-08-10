"""Smoke test: browser_manager discovery, caching, port selection.

Runs fast — no browser launch required for discovery tests.

    python tests/gpt_auto/test_browser_manager.py
"""

import asyncio
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def test_discover_browser() -> bool:  # type: ignore[return-value]
    """Discover the system default browser."""
    from audiagentic.foundation.system.browser_manager import discover_browser

    browser = discover_browser()
    if browser is None:
        print("FAIL — no default browser discovered")
        return False
    path = Path(browser)
    if not path.exists():
        print(f"FAIL — discovered browser path does not exist: {browser}")
        return False
    print(f"OK — default browser: {path}")
    return True


def test_config_defaults() -> bool:  # type: ignore[return-value]
    """BrowserConfig defaults."""
    from audiagentic.foundation.system.browser_manager import BrowserConfig

    cfg = BrowserConfig()
    if cfg.port != 9222:
        print(f"FAIL — default port: {cfg.port}")
        return False
    if cfg.idle_timeout_seconds != 300.0:
        print(f"FAIL — default idle timeout: {cfg.idle_timeout_seconds}")
        return False
    if not cfg.auto_start:
        print(f"FAIL — default auto_start: {cfg.auto_start}")
        return False
    if not str(cfg.profile_dir).endswith("gpt-auto-profile"):
        print(f"FAIL — default profile dir: {cfg.profile_dir}")
        return False
    print(f"OK — config defaults (port={cfg.port}, profile={cfg.profile_dir})")
    return True


def test_get_or_discover_browser() -> bool:  # type: ignore[return-value]
    """Discover and cache browser path."""
    from audiagentic.foundation.system.browser_manager import (
        _config_file,
        _load_config,
        get_or_discover_browser,
    )

    with tempfile.TemporaryDirectory() as tmp:
        runtime_root = Path(tmp)
        try:
            browser = get_or_discover_browser(runtime_root)
        except RuntimeError as exc:
            print(f"FAIL — {exc}")
            return False

        path = Path(browser)
        if not path.exists():
            print(f"FAIL — returned path does not exist: {browser}")
            return False

        cfg_file = _config_file(runtime_root)
        if not cfg_file.exists():
            print("FAIL — config file not persisted")
            return False

        cfg = _load_config(runtime_root)
        if cfg.get("browser_path") != browser:
            print(f"FAIL — persisted path mismatch: {cfg}")
            return False

        cached = get_or_discover_browser(runtime_root)
        if cached != browser:
            print(f"FAIL — cache miss: expected {browser}, got {cached}")
            return False

        print(f"OK — discovered + cached: {path}")
        return True


def test_get_or_discover_invalid_cache() -> bool:  # type: ignore[return-value]
    """Stale cached path triggers re-discovery."""
    from audiagentic.foundation.system.browser_manager import (
        _save_config,
        get_or_discover_browser,
    )

    with tempfile.TemporaryDirectory() as tmp:
        runtime_root = Path(tmp)
        _save_config({"browser_path": "/nonexistent/browser.exe"}, runtime_root)

        try:
            browser = get_or_discover_browser(runtime_root)
        except RuntimeError as exc:
            print(f"FAIL — re-discovery failed: {exc}")
            return False

        path = Path(browser)
        if not path.exists():
            print(f"FAIL — re-discovered path does not exist: {browser}")
            return False

        print(f"OK — stale cache invalidated, re-discovered: {path}")
        return True


def test_port_available() -> bool:  # type: ignore[return-value]
    """Check port availability check works."""
    from audiagentic.foundation.system.browser_manager import _is_port_available

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]

    async def _check() -> bool:
        available = await _is_port_available(port)
        return not available  # Should be False (occupied)

    try:
        result = asyncio.run(_check())
        if not result:
            print("FAIL — port availability check incorrect")
            return False

        async def _check_free() -> bool:
            return await _is_port_available(59876)

        free = asyncio.run(_check_free())
        if not free:
            print(f"FAIL — free port {59876} incorrectly marked as occupied")
            return False

        print(f"OK — port {port} correctly detected as occupied")
        return True
    finally:
        s.close()


def test_find_available_port() -> bool:  # type: ignore[return-value]
    """Auto-select finds the first free port."""
    from audiagentic.foundation.system.browser_manager import find_available_port

    base = 59870
    sockets = []
    for i in range(3):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", base + i))
        sockets.append(s)

    async def _check() -> bool:
        port = await find_available_port(base)
        return port == base + 3  # First free after 3 occupied

    try:
        result = asyncio.run(_check())
        if not result:
            print(f"FAIL — expected {base + 3}, got incorrect port")
            return False
        print(f"OK — auto-selected {base + 3} (skipped {base}-{base + 2})")
        return True
    finally:
        for s in sockets:
            s.close()


def test_find_available_port_default() -> bool:  # type: ignore[return-value]
    """Auto-select starts from given port."""
    from audiagentic.foundation.system.browser_manager import find_available_port

    async def _check() -> bool:
        port = await find_available_port(59900)
        return port >= 59900

    result = asyncio.run(_check())
    if not result:
        print("FAIL — default search failed")
        return False
    print("OK — auto-selected from default range")
    return True


def main() -> bool:
    """Run all tests."""
    tests = [
        ("discover_browser", test_discover_browser),
        ("config_defaults", test_config_defaults),
        ("get_or_discover_browser", test_get_or_discover_browser),
        ("get_or_discover_invalid_cache", test_get_or_discover_invalid_cache),
        ("port_available", test_port_available),
        ("find_available_port", test_find_available_port),
        ("find_available_port_default", test_find_available_port_default),
    ]

    passed = 0
    failed = 0

    for name, fn in tests:
        print(f"\n--- {name} ---")
        try:
            if fn():
                passed += 1
            else:
                failed += 1
        except Exception as exc:
            print(f"ERROR — {exc}")
            import traceback

            traceback.print_exc()
            failed += 1

    print(f"\n{'=' * 40}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")

    if failed:
        print("FAIL")
        return False
    print("ALL OK")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
