"""Small provider-side interpretation of a tagged prompt header.

This module deliberately does not validate a tag or create a job.  Those are
requester-owned actions.  Provider adapters only need stable first-line
semantics to preserve prompt provenance and prepare their native request.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaggedPrompt:
    """Primitive values extracted from the first non-empty prompt line."""

    tag: str
    directives: dict[str, str]
    body: str


def parse_tagged_prompt(raw_prompt: str) -> TaggedPrompt | None:
    """Extract an ``@tag`` header from only the first non-empty line.

    The raw prompt is intentionally not normalised here.  Callers retain it
    for provenance, while ``body`` is the text below the header for native CLI
    execution where the tag is already represented in caller metadata.
    """
    lines = raw_prompt.splitlines()
    first_index = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_index is None:
        return None
    tokens = lines[first_index].strip().split()
    if not tokens or not tokens[0].startswith("@") or len(tokens[0]) == 1:
        return None

    directives: dict[str, str] = {}
    for token in tokens[1:]:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key and value:
            directives[key] = value
    return TaggedPrompt(
        tag=tokens[0],
        directives=directives,
        body="\n".join(lines[first_index + 1 :]).lstrip("\n"),
    )
