"""Smoke test: browser_manager discovery and basic lifecycle.

Runs fast — no browser launch required for discovery tests.

    python tests/gpt_auto/test_browser_manager.py
"""
import asyncio
import sys
import tempfile
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))


def test_discover_browser() -> None:
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


def test_get_or_discover_browser() -> None:
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

        # Check persistence
        cfg_file = _config_file(runtime_root)
        if not cfg_file.exists():
            print("FAIL — config file not persisted")
            return False

        cfg = _load_config(runtime_root)
        if cfg.get("browser_path") != browser:
            print(f"FAIL — persisted path mismatch: {cfg}")
            return False

        # Cached lookup should skip discovery
        cached = get_or_discover_browser(runtime_root)
        if cached != browser:
            print(f"FAIL — cache miss: expected {browser}, got {cached}")
            return False

        print(f"OK — discovered + cached: {path}")
        return True


def test_get_or_discover_invalid_cache() -> None:
    """Stale cached path triggers re-discovery."""
    from audiagentic.foundation.system.browser_manager import (
        _save_config,
        get_or_discover_browser,
    )

    with tempfile.TemporaryDirectory() as tmp:
        runtime_root = Path(tmp)
        # Write a stale path that doesn't exist
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


def test_config_defaults() -> None:
    """BrowserConfig defaults."""
    from audiagentic.foundation.system.browser_manager import BrowserConfig

    cfg = BrowserConfig()
    if cfg.port != 9222:
        print(f"FAIL — default port: {cfg.port}")
        return False
    if cfg.idle_timeout_seconds != 300.0:
        print(f"FAIL — default idle timeout: {cfg.idle_timeout_seconds}")
        return False
    if cfg.auto_start is not True:
        print(f"FAIL — default auto_start: {cfg.auto_start}")
        return False
    if not str(cfg.profile_dir).endswith("gpt-auto-profile"):
        print(f"FAIL — default profile dir: {cfg.profile_dir}")
        return False

    print(f"OK — config defaults correct (port={cfg.port}, profile={cfg.profile_dir})")
    return True


def test_port_available() -> None:
    """Check port availability check works."""
    import socket

    from audiagentic.foundation.system.browser_manager import _is_port_available

    # Bind to a random high port, then check it's not available
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    
    async def _check():
        occupied = await _is_port_available(port)
        return not occupied  # Should be False (occupied)

    result = asyncio.run(_check())
    if not result:
        print("FAIL — port availability check incorrect")
        return False

    print(f"OK — port {port} correctly detected as occupied")
    return True


def main() -> bool:
    """Run all tests."""
    tests = [
        ("discover_browser", test_discover_browser),
        ("config_defaults", test_config_defaults),
        ("get_or_discover_browser", test_get_or_discover_browser),
        ("get_or_discover_invalid_cache", test_get_or_discover_invalid_cache),
        ("port_available", test_port_available),
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

    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)}")

    if failed:
        print("FAIL")
        return False
    print("ALL OK")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
