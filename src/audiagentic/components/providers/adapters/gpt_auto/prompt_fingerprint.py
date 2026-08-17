"""Tolerant prompt/DOM-text correlation for gpt-auto (GP25).

Replaces three previously-inconsistent equality definitions (turn.py's
_matches()/_normal(), chat.py's _same_prompt() and _prompt_text_digest())
with one shared primitive. ChatGPT's renderer strips Markdown presentation
syntax (fenced/inline code backticks, link brackets) from the DOM text it
shows relative to the originally-submitted source, so exact-string
comparison against DOM-observed text intermittently and unpredictably
fails on long/code-heavy prompts -- confirmed live three times (a
bigcherry incident, GP10's re-consultation req_1250368b8f2f4477, and
GP24/GP30's own code-dense design-consultation prompt, 2026-08-16/17).

Case, indentation, and interior whitespace remain semantically significant
for coding prompts and are deliberately preserved here -- only the Markdown
presentation syntax itself is stripped, never blanket whitespace collapsing.

KNOWN RESIDUAL GAP (found live 2026-08-17, req_27c9251fa0c54d73): ChatGPT's
renderer does two things this module does not yet fully compensate for on
very long, multi-code-block prompts: (1) it displays a fenced block's
language tag (e.g. the "python" in ```python) as its own visible text
line rather than discarding it -- handled below by keeping the language
word instead of stripping it entirely; (2) it re-encodes a code block's
leading indentation as alternating non-breaking-space/space pairs that do
NOT preserve the original character count 1:1 (e.g. three plain spaces
can become "\xa0 \xa0", a different length) -- NOT yet handled, since a
generic fix would mean collapsing interior whitespace runs, contradicting
this module's deliberate indentation-preservation design. Left as a
documented, real, still-open limitation rather than papered over.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_FENCE_OPEN_RE = re.compile(r"```([^\n]*)\n")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")


def _replace_fence_open(match: re.Match[str]) -> str:
    # ChatGPT's UI renders a fenced block's language tag as its own visible
    # text line (a syntax-highlighter label) rather than discarding it --
    # keep the language word, strip only the backtick delimiters themselves.
    language = match.group(1)
    return f"{language}\n" if language else ""


def normalize_prompt_text(text: str) -> str:
    """Reduce text to a form tolerant of ChatGPT's Markdown-stripping rendering."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").removesuffix("\n")
    # Fenced code blocks: strip the ``` delimiters (keeping any language
    # tag as visible text, see _replace_fence_open), keeping the code
    # content -- including its internal whitespace and indentation --
    # otherwise unchanged.
    normalized = _FENCE_OPEN_RE.sub(_replace_fence_open, normalized)
    normalized = normalized.replace("```", "")
    # Inline code backticks.
    normalized = normalized.replace("`", "")
    # Markdown links: [text](url) -> text.
    normalized = _LINK_RE.sub(r"\1", normalized)
    return normalized


@dataclass(frozen=True)
class PromptFingerprint:
    """A durable, comparable fingerprint of a submitted prompt's text."""

    digest: str

    @classmethod
    def from_text(cls, text: str) -> PromptFingerprint:
        normalized = normalize_prompt_text(text)
        return cls(hashlib.sha256(normalized.encode("utf-8")).hexdigest())

    def matches_text(self, text: str) -> bool:
        return self == PromptFingerprint.from_text(text)


def match_prompt(expected: str, observed: str) -> bool:
    """Tolerant one-shot prompt/DOM-text comparison."""
    return normalize_prompt_text(expected) == normalize_prompt_text(observed)
