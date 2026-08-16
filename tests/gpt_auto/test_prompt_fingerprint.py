"""GP25: shared prompt/DOM-text correlation primitive.

Replaces turn.py's _matches()/_normal(), chat.py's _same_prompt() and
_prompt_text_digest() with one consistent tolerant-match definition.
"""

from __future__ import annotations

from audiagentic.components.providers.adapters.gpt_auto.prompt_fingerprint import (
    PromptFingerprint,
    match_prompt,
    normalize_prompt_text,
)


def test_normalize_preserves_case_spacing_and_indentation() -> None:
    """Case, indentation, and interior whitespace remain semantically
    significant for coding prompts -- only Markdown syntax is stripped."""
    assert normalize_prompt_text("Return Foo") != normalize_prompt_text("return foo")
    assert normalize_prompt_text("x  y") != normalize_prompt_text("x y")
    assert normalize_prompt_text("if ok:\n    run()") != normalize_prompt_text("if ok:\nrun()")
    assert normalize_prompt_text("line\r\n") == "line"


def test_normalize_strips_inline_code_backticks() -> None:
    assert normalize_prompt_text("call `foo()` now") == normalize_prompt_text("call foo() now")


def test_normalize_strips_fenced_code_block_markers_keeping_content() -> None:
    submitted = "Review this:\n```python\ndef f():\n    return 1\n```\nThanks"
    rendered = "Review this:\ndef f():\n    return 1\nThanks"
    assert normalize_prompt_text(submitted) == normalize_prompt_text(rendered)
    # The code content itself, including its indentation, survives intact.
    assert "    return 1" in normalize_prompt_text(submitted)


def test_normalize_strips_markdown_link_syntax() -> None:
    assert normalize_prompt_text("see [the docs](https://example.com/x)") == normalize_prompt_text(
        "see the docs"
    )


def test_match_prompt_tolerant_of_markdown_stripping() -> None:
    submitted = "Check `config.py` and the `turn.py` file for `_matches()`."
    rendered = "Check config.py and the turn.py file for _matches()."
    assert match_prompt(submitted, rendered)


def test_match_prompt_still_rejects_genuinely_different_text() -> None:
    assert not match_prompt("do the first thing", "do the second thing")


def test_fingerprint_matches_text_consistent_with_match_prompt() -> None:
    submitted = "run `pytest -q` please"
    rendered = "run pytest -q please"
    fingerprint = PromptFingerprint.from_text(submitted)
    assert fingerprint.matches_text(rendered)
    assert fingerprint == PromptFingerprint.from_text(rendered)


def test_real_incident_delta_gp10_resubmission_2324_vs_2306_chars() -> None:
    """GP19/GP10 live incident (req_1250368b8f2f4477): a long multi-paragraph
    prompt with an 18-char delta between typed-text-length (2324) and
    expected-prompt-length (2306) never matched under the old exact-text
    comparison. Reproduce the same shape here: backtick-heavy text whose
    rendered form is shorter than the submitted Markdown source."""
    submitted = (
        "Please review `GptAutoConfig.from_dict()` and `GptAutoConfig.from_project_dict()` "
        "in `config.py`, along with `deep_merge()` and `_load_packaged_defaults()`. "
        "Also check `session_transport.py`'s call site and `defaults.yaml`."
    )
    # ChatGPT's renderer strips the backticks around each identifier.
    rendered = (
        "Please review GptAutoConfig.from_dict() and GptAutoConfig.from_project_dict() "
        "in config.py, along with deep_merge() and _load_packaged_defaults(). "
        "Also check session_transport.py's call site and defaults.yaml."
    )
    assert len(submitted) != len(rendered)
    assert match_prompt(submitted, rendered)


def test_backward_incompatible_with_old_exact_digest_is_a_known_accepted_tradeoff() -> None:
    """A durable unresolved_prompt_text_digest computed by the OLD algorithm
    (whitespace-collapse only, no Markdown stripping) will not match a
    digest computed by the new PromptFingerprint after this deploys -- this
    is an accepted, self-recovering tradeoff (surfaces as a clear
    EXT-GPTAUTO-004 reconciliation error, never silent data corruption),
    not something this primitive needs to paper over. Documented here so
    the behavior is intentional, not accidental."""
    import hashlib
    import re

    def _old_prompt_text_digest(value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip()
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    text = "call `foo()` now"
    assert _old_prompt_text_digest(text) != PromptFingerprint.from_text(text).digest
