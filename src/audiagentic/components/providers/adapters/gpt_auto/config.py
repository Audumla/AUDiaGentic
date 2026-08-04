"""Configuration for the gpt-auto provider."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Known ChatGPT model identifiers (display names used in the UI)
KNOWN_MODELS = frozenset(
    {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.5-preview",
        "o3-mini",
        "o4-mini",
    }
)


@dataclass(frozen=True)
class GptAutoConfig:
    """Runtime configuration for the gpt-auto provider.

    All settings are local — no API keys or remote connectivity required.
    """

    # --- Browser / target ---
    target_url: str = "chat.openai.com"
    """Hostname to look for when enumerating tabs."""

    model_select: str | None = None
    """If set, the model name shown in ChatGPT's model selector (e.g. 'gpt-4o').
    The user must have this model available in their ChatGPT session."""

    # --- Timing ---
    tab_selection_timeout: int = 10
    """Seconds to wait for the target ChatGPT tab to appear/load."""

    login_timeout: int = 120
    """Maximum seconds to wait for the user to complete login if prompted."""

    response_wait_timeout: int = 120
    """Maximum seconds to poll for a response from ChatGPT's DOM."""

    polling_interval: float = 2.0
    """Seconds between DOM polls while waiting for a response."""

    typing_speed: float = 0.02
    """Seconds between keystrokes when injecting the prompt (human-like)."""

    # --- Connection ---
    profile_dir: str | None = None
    """Persistent profile directory for ChatGPT cookies. Defaults to ~/.gpt-auto-profile."""

    browser_path: str | None = None
    """Path to a specific Chrome/Chromium executable. Auto-detected if omitted."""

    def __post_init__(self) -> None:
        if self.model_select is not None and self.model_select not in KNOWN_MODELS:
            logger.warning(
                "model_select=%r not in known models %s — will still be used for display only",
                self.model_select,
                KNOWN_MODELS,
            )

    @classmethod
    def from_dict(cls, data: dict) -> GptAutoConfig:
        """Create config from a dictionary (e.g. provider descriptor YAML)."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
