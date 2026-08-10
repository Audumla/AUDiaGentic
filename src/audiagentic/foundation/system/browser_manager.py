"""Cross-platform browser launch and lifecycle for CDP-based providers.

Uses ``foundation.system.managed_process`` for lifecycle ownership with PID
evidence and platform-native discovery for the default browser path.  The
provider owns the browser process — it starts on first use, stays alive across
sessions, and stops when idle or the provider unloads.

Port conflicts fail gracefully; existing processes on the port are never killed.
The discovered browser path is persisted in the runtime config so repeated
launches don't re-probe.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from audiagentic.foundation.system.managed_process import (
    DetachedLaunch,
    ProcessEvidence,
    launch_detached,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Browser path persistence
# ---------------------------------------------------------------------------


def _config_dir(runtime_root: Path | None = None) -> Path:
    """Return the runtime config directory, creating it if needed."""
    root = runtime_root or Path.home()
    cfg = root / ".audiagentic" / "runtime"
    cfg.mkdir(parents=True, exist_ok=True)
    return cfg


def _config_file(runtime_root: Path | None = None) -> Path:
    return _config_dir(runtime_root) / "browser_config.json"


def _load_config(runtime_root: Path | None = None) -> dict[str, Any]:
    cfg = _config_file(runtime_root)
    if not cfg.exists():
        return {}
    try:
        return json.loads(cfg.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.debug("failed to read browser config", exc_info=True)
        return {}


def _save_config(data: dict[str, Any], runtime_root: Path | None = None) -> None:
    cfg = _config_file(runtime_root)
    try:
        cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        logger.debug("failed to persist browser config", exc_info=True)


# ---------------------------------------------------------------------------
# Browser discovery — system default only, no fallbacks
# ---------------------------------------------------------------------------


def _discover_browser_windows() -> str | None:
    """Discover the default browser on Windows via registry.

    Modern browsers use UWP-style ProgIds (BraveHTML, ChromeHTML) that point to
    an Application subkey with AppUserModelId.  Legacy browsers use shell\open\command.
    Both paths are supported.
    """
    import winreg

    # Default HTTP handler → ProgId
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice",
        )
        prog_id: str = winreg.QueryValueEx(key, "ProgId")[0]  # type: ignore[assignment]
        winreg.CloseKey(key)
    except OSError:
        return None

    # Modern: ProgId → Application\AppUserModelId → App Paths registry
    try:
        app_key = winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT,
            rf"{prog_id}\Application",
        )
        app_user_model_id: str = winreg.QueryValueEx(app_key, "AppUserModelId")[0]  # type: ignore[assignment]
        winreg.CloseKey(app_key)

        # Extract executable name from AppUserModelId (e.g. "Brave" → "brave.exe")
        exe_name = app_user_model_id.split(".")[-1].lower() + ".exe"
        app_paths_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}",
        )
        exe: str = winreg.QueryValueEx(app_paths_key, None)[0]  # type: ignore[assignment]
        winreg.CloseKey(app_paths_key)
        if Path(exe).exists():
            return exe
    except OSError:
        pass

    # Legacy: ProgId → shell\open\command
    try:
        cmd_key = winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT,
            rf"{prog_id}\shell\open\command",
        )
        exe_and_args: str = winreg.QueryValueEx(cmd_key, None)[0]  # type: ignore[assignment]
        winreg.CloseKey(cmd_key)
        exe = exe_and_args.strip().strip('"').split()[0]
        if Path(exe).exists():
            return exe
    except OSError:
        pass

    return None


def _discover_browser_macos() -> str | None:
    """Discover the default browser on macOS via defaults."""
    try:
        result = subprocess.run(
            ["/usr/bin/defaults", "read", "-g", "AppleDefaultWebBrowser"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            bundle_id = result.stdout.strip()
            # Resolve bundle ID to app path via mdfind
            locate_result = subprocess.run(
                ["mdfind", "-name", bundle_id],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if locate_result.returncode == 0:
                app_path = locate_result.stdout.strip().split("\n")[0]
                # Find executable in Contents/MacOS/
                exe_dir = Path(app_path) / "Contents" / "MacOS"
                if exe_dir.is_dir():
                    for item in exe_dir.iterdir():
                        if item.is_file() and os.access(item, os.X_OK):
                            return str(item)
    except (subprocess.TimeoutExpired, OSError):
        pass

    return None


def _discover_browser_linux() -> str | None:
    """Discover the default browser on Linux via xdg-settings."""
    try:
        result = subprocess.run(
            ["xdg-settings", "get", "default-web-browser"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            desktop_file = result.stdout.strip()
            # Resolve .desktop file to executable
            for base in [
                Path.home() / ".local/share/applications",
                Path("/usr/share/applications"),
            ]:
                dp = base / desktop_file
                if dp.exists():
                    content = dp.read_text(encoding="utf-8", errors="replace")
                    for line in content.splitlines():
                        if line.startswith("Exec="):
                            exe = line[5:].split("%")[0].strip()
                            parts = exe.split()
                            # Skip env vars, find actual executable
                            for p in parts:
                                if "=" not in p and p.startswith("/"):
                                    if Path(p).exists():
                                        return p
                            break
    except (subprocess.TimeoutExpired, OSError):
        pass

    return None


def discover_browser(runtime_root: Path | None = None) -> str | None:
    """Discover the system default browser.

    Uses platform-native methods only — no fallbacks, no PATH searching.
    Returns the path to the browser executable or None if discovery fails.
    """
    if sys.platform == "win32":
        return _discover_browser_windows()
    elif sys.platform == "darwin":
        return _discover_browser_macos()
    else:
        return _discover_browser_linux()


def get_or_discover_browser(runtime_root: Path | None = None) -> str:
    """Return cached browser path or discover and cache it.

    Loads from persisted config first. If missing or the stored path no longer
    exists, re-discover via platform-native methods and persist the result.

    Raises:
        RuntimeError: If no default browser can be found.
    """
    cfg = _load_config(runtime_root)
    cached_path = cfg.get("browser_path")

    # Validate cached path still exists
    if cached_path and Path(cached_path).exists():
        return cached_path

    # Discover fresh — system default only
    browser = discover_browser(runtime_root)
    if not browser:
        raise RuntimeError(
            "No default browser found. Set the system default browser or configure "
            "``browser_path`` in the gpt-auto provider config."
        )

    cfg["browser_path"] = browser
    _save_config(cfg, runtime_root)
    return browser


# ---------------------------------------------------------------------------
# Browser lifecycle
# ---------------------------------------------------------------------------


@dataclass
class BrowserConfig:
    """Configuration for the managed browser instance."""

    port: int = 9222
    """TCP port for the managed browser's CDP endpoint.

    Set to 0 to auto-select an available port starting from 9222.
    The selected port is persisted in the runtime config for reuse.
    """
    profile_dir: Path | None = None
    idle_timeout_seconds: float = 300.0
    auto_start: bool = True
    runtime_root: Path | None = None

    # No default profile_dir — use the browser's DEFAULT profile by default.
    # Only set profile_dir when an isolated profile is explicitly requested.


def _browser_command(browser_path: str, config: BrowserConfig) -> tuple[str, ...]:
    """Build the browser launch command with CDP flags.

    Minimal flags — uses default profile so existing logins survive.
    Only adds ``--user-data-dir`` if an isolated profile is explicitly configured.
    """
    cmd: list[str] = [
        browser_path,
        f"--remote-debugging-port={config.port}",
        "--no-first-run",
    ]
    if config.profile_dir is not None:
        cmd.append(f"--user-data-dir={config.profile_dir}")
    return tuple(cmd)


async def _is_port_available(port: int) -> bool:
    """Check if a TCP port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
            return True
    except OSError:
        return False


async def find_available_port(start: int = 9222, max_tries: int = 50) -> int:
    """Find the first available TCP port starting from *start*.

    Returns the port number. Raises RuntimeError if none of the ports are free.
    """
    for port in range(start, start + max_tries):
        if await _is_port_available(port):
            return port
    raise RuntimeError(
        f"No available port found in range {start}-{start + max_tries - 1}. "
        "Configure ``browser_port`` to a specific free port."
    )


async def _is_cdp_responding(port: int, timeout: float = 3.0) -> bool:
    """Check if a CDP endpoint is already responding on *port*."""
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        await asyncio.sleep(0.2)
    return False


async def _wait_for_browser_ready(port: int, timeout: float = 30.0) -> bool:
    """Poll the CDP endpoint until the browser responds."""
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            pass
        await asyncio.sleep(0.5)

    return False


@dataclass
class BrowserManager:
    """Manages a single browser instance with cross-platform support.

    Lifecycle:
    - ``start()`` discovers browser binary (cached), launches it, waits for CDP readiness
    - ``is_browser_running`` checks if the managed browser is still alive
    - ``stop()`` terminates the browser process tree
    - ``__aenter__``/``__aexit__`` context manager support
    """

    config: BrowserConfig = field(default_factory=BrowserConfig)
    _browser_path: str | None = None
    _evidence: ProcessEvidence | None = None
    _cdp_url: str | None = None
    _last_active_at: float | None = None

    @property
    def browser_path(self) -> str | None:
        """Path to the discovered browser executable."""
        return self._browser_path

    @property
    def cdp_url(self) -> str | None:
        """CDP endpoint URL if browser is running."""
        return self._cdp_url

    @property
    def is_browser_running(self) -> bool:
        """Whether the managed browser process is still alive."""
        if self._evidence is None:
            return False
        from audiagentic.foundation.system.process import pid_alive

        return pid_alive(self._evidence.pid)

    async def start(self, *, owner_epoch: str | None = None) -> str:
        """Start the browser and wait for CDP readiness.

        Returns:
            The CDP URL (e.g. ``http://127.0.0.1:9222``).

        Raises:
            RuntimeError: If browser binary not found or port unavailable.
        """
        if self.is_browser_running and self._cdp_url:
            self._last_active_at = time.monotonic()
            return self._cdp_url

        # Resolve port — auto-select if 0, otherwise use configured value
        base_port = self.config.port
        port = await find_available_port(base_port) if base_port == 0 else base_port

        # Port occupied — fail, don't kill existing processes
        if not await _is_port_available(port):
            raise RuntimeError(
                f"Port {port} is already in use. "
                "The gpt-auto provider cannot launch a browser on an occupied port. "
                "Configure ``browser_port`` to 0 for auto-select or use a different port."
            )

        # Discover browser — system default only, fails if not found
        self._browser_path = get_or_discover_browser(self.config.runtime_root)

        logger.info(
            "gpt-auto browser launch begin browser=%s port=%d profile=%s",
            self._browser_path,
            self.config.port,
            self.config.profile_dir,
        )

        # Ensure profile directory exists
        if self.config.profile_dir:
            self.config.profile_dir.mkdir(parents=True, exist_ok=True)

        # Build and launch command
        cmd = _browser_command(self._browser_path, self.config)
        logger.info("gpt-auto browser command: %s", " ".join(cmd))

        # Launch as detached managed process
        epoch = owner_epoch or f"browser-{time.monotonic()}"
        evidence = launch_detached(
            DetachedLaunch(command=cmd),
            owner_epoch=epoch,
        )
        self._evidence = evidence
        self._cdp_url = f"http://127.0.0.1:{self.config.port}"

        # Wait for CDP readiness — fail if browser doesn't respond
        ready = await _wait_for_browser_ready(self.config.port)
        if not ready:
            logger.error("gpt-auto browser did not become ready on port %d", self.config.port)
            await self.stop()
            raise RuntimeError(
                f"Browser {self._browser_path} failed to start on port {self.config.port}"
            )

        self._last_active_at = time.monotonic()
        logger.info("gpt-auto browser ready pid=%d cdp=%s", evidence.pid, self._cdp_url)
        return self._cdp_url

    async def stop(self) -> None:
        """Terminate the managed browser process tree."""
        if self._evidence is None or not self.is_browser_running:
            return

        from audiagentic.foundation.system.managed_process import (
            observe_process,
            signal_owned_process,
        )

        observed = observe_process(self._evidence)
        try:
            signal_owned_process(self._evidence, observed, force=True)
        except Exception:
            logger.warning("gpt-auto browser stop failed (best-effort)", exc_info=True)

        self._evidence = None
        self._cdp_url = None
        logger.info("gpt-auto browser stopped")

    def touch(self) -> None:
        """Record activity to prevent idle timeout."""
        self._last_active_at = time.monotonic()

    def is_idle(self) -> bool:
        """Check if the browser has been idle past its timeout."""
        if self._last_active_at is None:
            return True
        return (time.monotonic() - self._last_active_at) > self.config.idle_timeout_seconds

    async def __aenter__(self) -> BrowserManager:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()


__all__ = [
    "BrowserConfig",
    "BrowserManager",
    "discover_browser",
    "get_or_discover_browser",
]
