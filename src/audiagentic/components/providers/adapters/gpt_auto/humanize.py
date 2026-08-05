"""Human-like timing utilities for gpt-auto browser automation.

ChatGPT's bot detection reacts to uniform, machine-like timing (same prompt,
same delays, instant submit).  These helpers produce variable, human-plausible
delays: per-character typing cadence with occasional pauses, a "thinking"
pause before pressing send, and a pause before reading the response.
"""

from __future__ import annotations

import random


def jittered(base: float, jitter: float = 0.3, min_value: float = 0.0) -> float:
    """Return *base* seconds with uniform random jitter.

    ``jitter`` is the +/- fraction (e.g. 0.3 = +/-30%).  Result is clamped to
    >= ``min_value``.
    """
    low = max(base * (1.0 - jitter), min_value)
    high = max(base * (1.0 + jitter), min_value)
    return random.uniform(low, high)


def typing_delays(
    text_length: int,
    char_mean: float = 0.07,
    char_jitter: float = 0.5,
    pause_every: int = 12,
    pause_max: float = 0.9,
) -> list[float]:
    """Build a per-character delay schedule for typing *text_length* chars.

    Simulates a human typist: most characters land at ``char_mean`` +/- jitter,
    but every ``pause_every`` characters there is a short hesitation (like a
    pause to think or correct).
    """
    delays: list[float] = []
    for i in range(text_length):
        delay = jittered(char_mean, char_jitter, min_value=0.01)
        if pause_every > 0 and i > 0 and i % pause_every == 0:
            delay += random.uniform(0.1, pause_max)
        delays.append(delay)
    return delays


def think_delay(min_seconds: float = 1.5, max_seconds: float = 6.0) -> float:
    """Pause before pressing send — simulating reading the prompt back."""
    return random.uniform(min_seconds, max_seconds)


def post_send_pause(min_seconds: float = 1.0, max_seconds: float = 3.5) -> float:
    """Pause after submitting, before starting to poll the response."""
    return random.uniform(min_seconds, max_seconds)


def between_requests_delay(min_seconds: float = 8.0, max_seconds: float = 20.0) -> float:
    """Pause between successive requests in a continuous conversation."""
    return random.uniform(min_seconds, max_seconds)
