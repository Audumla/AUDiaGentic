"""Configuration for the gpt-auto provider (CDP connect approach)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GptAutoConfig:
    """Runtime configuration for the gpt-auto CDP provider.

    All settings are local — no API keys or remote connectivity required.
    Connects to an already-running Chrome/Brave via DevTools Protocol.
    """

    # --- Browser / target ---
    target_url: str = "chat.openai.com"
    """Hostname to look for when enumerating tabs."""

    model_select: str | None = None
    """If set, the model name shown in ChatGPT's model selector (e.g. 'gpt-4o')."""

    # --- Managed browser lifecycle ---
    browser_port: int = 9222
    """TCP port for the managed browser's CDP endpoint.

    If ``browser_autostart`` is True and no browser is listening on this port,
    the provider launches one using the system default browser.  The port must
    be free — existing listeners are never killed.
    """

    browser_profile_dir: str | None = None
    """Path to the browser user-data directory (isolated profile).

    Defaults to ``~/.audiagentic/runtime/gpt-auto-profile`` when omitted.
    Persists between gateway restarts so sessions survive process death.
    """

    browser_autostart: bool = True
    """Whether the provider should launch its own browser instance.

    When False the provider connects to an already-running browser on
    ``browser_port``.  When True (default) the provider discovers the system
    default browser, launches it with CDP flags, and manages its lifecycle.
    """

    browser_idle_timeout_seconds: float = 300.0
    """Seconds of inactivity before the managed browser is stopped."""

    # --- CDP connection ---
    cdp_url: str = "http://127.0.0.1:9222"
    """Chrome DevTools Protocol URL of the running browser.

    Deprecated when ``browser_autostart`` is True — derived from ``browser_port`` instead.
    """

    # --- Browser lifecycle aliases ---

    # --- Timing ---
    tab_selection_timeout: int = 15
    """Seconds to wait for the target ChatGPT tab to appear/load."""

    login_timeout: int = 0
    """Deprecated compatibility field; login waiting is disabled."""

    response_wait_timeout: int = 120
    """Maximum seconds to poll for a response from ChatGPT's DOM."""

    polling_interval: float = 2.0
    """Seconds between DOM polls while waiting for a response."""

    typing_speed: float = 0.03
    """Seconds between keystrokes when injecting the prompt (human-like)."""

    response_stability_seconds: float = 6.0
    """Seconds of unchanged text needed before declaring a response complete.

    The streaming indicator flickers during inter-chunk pauses and the
    reasoning phase, so completion is decided by a stability window: the
    response is only returned when its text has been unchanged for this
    duration.  Tests may set this to a small value (e.g. 1.5) to reduce
    wall-clock time.
    """

    _KEY_ALIASES = {
        "response-timeout": "response_wait_timeout",
        "typing-speed": "typing_speed",
        "tab-selection-timeout": "tab_selection_timeout",
        "login-timeout": "login_timeout",
        "response-stability-seconds": "response_stability_seconds",
        "browser-port": "browser_port",
        "browser-profile-dir": "browser_profile_dir",
        "browser-autostart": "browser_autostart",
        "browser-idle-timeout-seconds": "browser_idle_timeout_seconds",
    }

    @classmethod
    def from_dict(cls, data: dict) -> GptAutoConfig:
        """Create config from a dictionary (e.g. provider descriptor YAML).

        Normalizes hyphenated keys to underscore field names via an alias map
        so YAML conventions are respected without duplicating every key name.
        """
        mapped = {}
        for k, v in data.items():
            target = cls._KEY_ALIASES.get(k, k)
            if target in cls.__dataclass_fields__:
                mapped[target] = v
        return cls(**mapped)
