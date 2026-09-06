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

Case and non-whitespace content remain semantically significant for coding
prompts and are deliberately preserved here. Runs of horizontal whitespace
are deliberately NOT preserved exactly -- see GP43 below -- but this exists
purely to correlate "did the right content reach ChatGPT," not to verify
byte-perfect formatting was retained; the assistant reads and responds to
semantic content, not exact indentation width.

RESOLVED (GP43, 2026-08-17, root-caused live against a real 35850-char
diff-heavy prompt, req_c4c7f7b3ac03444b): ChatGPT's renderer re-encodes
runs of horizontal whitespace inside rendered message text using a mix of
non-breaking-space (\xa0) substitution and outright collapsing that does
NOT preserve the original run length 1:1 -- confirmed live: a lone leading
space becomes a lone \xa0 (length-preserving), but a run of 9 plain spaces
was observed collapsed to a single \xa0 (length-losing), and this pattern
recurs throughout a code/diff-heavy prompt, not just in leading
indentation. A byte-level diff against the real observed DOM text proved
this affects roughly 1 in 34 characters of a diff-heavy prompt and made
exact-length comparison fundamentally unreliable for such prompts. The
original design intent of preserving exact interior whitespace was based
on an incorrect assumption about ChatGPT's rendering fidelity; collapsing
any run of 2+ horizontal-whitespace characters (after normalizing \xa0 to
a plain space) to one canonical space closes the gap exactly -- verified
against that same 35850-char capture to produce a byte-for-byte match.

RESOLVED (GP44, 2026-08-17, root-caused live against req_42f9580ebfcd45d6 -- a
design-consultation prompt containing one fenced code block): a request
was observed stuck indefinitely in submission-proof (never reaching
completion detection) despite ChatGPT having received and fully answered
the real prompt minutes earlier. Reconstructing the exact submitted prompt
and the exact observed DOM text and diffing them found only two residual
mismatches: ChatGPT's renderer inserts an extra blank line immediately
before and after a fenced code block's rendered content (blank-line
padding around the code block), which _WS_RUN_RE (horizontal-only) does
not touch. Collapsing any run of 2+ newlines to one closes this exactly --
verified byte-for-byte against that capture. Vertical whitespace (blank
lines) carries no more submission-correlation meaning than horizontal
whitespace runs do; the same "compare content, not formatting fidelity"
rationale applies.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_FENCE_OPEN_RE = re.compile(r"```([^\n]*)\n")
_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# DOM text extraction can turn a single tab into a non-breaking space (and
# can otherwise choose any Unicode horizontal whitespace representation).
# Correlation cares about content and line boundaries, not the exact width or
# code point used for horizontal spacing, so canonicalise every horizontal
# run, including a single character.
_WS_RUN_RE = re.compile(r"[^\S\r\n]+")
_TRAILING_HWS_RE = re.compile(r"[ \t]+(?=\n|$)")
_BLANK_LINE_RUN_RE = re.compile(r"\n{2,}")


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
    # GP43/GP49: ChatGPT's renderer re-encodes horizontal whitespace (most
    # visibly leading indentation, but not only there) using a lossy mix of
    # tabs, non-breaking spaces, and outright collapsing.  Canonicalise every
    # horizontal run, including a single tab/NBSP, to one plain space.  This
    # only affects horizontal formatting; line boundaries and all
    # non-whitespace content remain significant.
    normalized = normalized.replace("\xa0", " ")
    # ChatGPT's message DOM strips trailing spaces from each rendered line,
    # while an admitted UTF-8 template can retain them at line endings.
    # They are presentation-only and must not make submission proof fail.
    normalized = _TRAILING_HWS_RE.sub("", normalized)
    normalized = _WS_RUN_RE.sub(" ", normalized)
    # GP44: ChatGPT's renderer pads a fenced code block with an extra blank
    # line immediately before and after its rendered content -- collapse
    # any run of 2+ newlines (blank lines) to one, the vertical analogue of
    # the horizontal-whitespace-run collapse above.
    normalized = _BLANK_LINE_RUN_RE.sub("\n", normalized)
    # The renderer drops all trailing blank lines, not just one newline.
    # Apply after whitespace normalization so whitespace-only final lines
    # cannot leave a residual newline and strand submission proof.
    return normalized.rstrip("\n")


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
