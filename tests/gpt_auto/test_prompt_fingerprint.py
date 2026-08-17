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


def test_normalize_preserves_case_and_presence_of_indentation() -> None:
    """Case and non-whitespace content remain semantically significant.
    Indentation DEPTH (present vs absent) is still distinguishable, but
    exact interior-whitespace RUN LENGTH is deliberately not (GP43) --
    ChatGPT's own renderer proved unable to preserve it reliably."""
    assert normalize_prompt_text("Return Foo") != normalize_prompt_text("return foo")
    assert normalize_prompt_text("if ok:\n    run()") != normalize_prompt_text("if ok:\nrun()")
    assert normalize_prompt_text("line\r\n") == "line"


def test_normalize_collapses_whitespace_runs_but_keeps_single_spaces_significant() -> None:
    """GP43 (2026-08-17, root-caused live against req_c4c7f7b3ac03444b's
    35850-char diff-heavy prompt): ChatGPT's renderer re-encodes horizontal
    whitespace runs using a lossy mix of non-breaking-space substitution
    and outright collapsing that does not preserve run length -- a byte-
    level diff against the real observed DOM text showed a run of 9 plain
    spaces collapsed to a single \\xa0. Exact-length comparison of interior
    whitespace RUNS is therefore fundamentally unreliable and is no longer
    attempted; a single space remains significant (still distinguishes
    "x y" from "xy"), and \\xa0 is treated exactly like a plain space."""
    assert normalize_prompt_text("x  y") == normalize_prompt_text("x y")
    assert normalize_prompt_text("x   y") == normalize_prompt_text("x \xa0 y")
    assert normalize_prompt_text("x y") != normalize_prompt_text("xy")


def test_normalize_strips_inline_code_backticks() -> None:
    assert normalize_prompt_text("call `foo()` now") == normalize_prompt_text("call foo() now")


def test_normalize_strips_fenced_code_block_markers_keeping_content() -> None:
    submitted = "Review this:\n```python\ndef f():\n    return 1\n```\nThanks"
    # The language tag survives as visible text (see the dedicated test for
    # that behavior) -- only the backtick delimiters themselves are gone.
    rendered = "Review this:\npython\ndef f():\n    return 1\nThanks"
    assert normalize_prompt_text(submitted) == normalize_prompt_text(rendered)
    # The code content itself survives -- indentation depth (present vs
    # absent) is preserved, but its exact run length is not (GP43): the
    # 4-space indent collapses to a single space, still distinguishing
    # the indented "return 1" line from an unindented one.
    assert " return 1" in normalize_prompt_text(submitted)
    assert "\nreturn 1" not in normalize_prompt_text(submitted)


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


def test_normalize_keeps_fenced_code_language_tag_as_visible_text() -> None:
    """Real live gap found 2026-08-17 (req_27c9251fa0c54d73): ChatGPT's
    renderer displays a fenced block's language tag (the "python" in
    ```python) as its own visible text line, a syntax-highlighter UI
    label -- it is not simply discarded like the rest of the fence syntax.
    Stripping it entirely (the original GP25 behavior) caused normalized
    submitted/observed text to permanently disagree on any prompt with a
    language-tagged fence."""
    submitted = "before\n```python\ndef f():\n    return 1\n```\nafter"
    # This approximates what ChatGPT's own rendering shows: the language
    # tag survives as a visible line, the backtick delimiters do not.
    rendered = "before\npython\ndef f():\n    return 1\nafter"
    assert normalize_prompt_text(submitted) == normalize_prompt_text(rendered)


def test_real_incident_gp43_diff_heavy_prompt_lossy_whitespace_reencoding() -> None:
    """GP43 (2026-08-17, req_c4c7f7b3ac03444b): a 35850-char diff-heavy
    review prompt was reported composer-typed-text-mismatch (33866 typed
    vs 35850 expected) and, separately, submission-proof-not-observed --
    the gateway's own status stayed 'running' for ~12 minutes before
    surfacing this as a hard failure, even though ChatGPT had already
    received and correctly answered the real prompt. Live DOM capture
    proved runs of leading indentation (observed: 9 plain spaces) were
    re-encoded by ChatGPT's renderer as a SINGLE \\xa0 -- not a 1:1
    NBSP-for-space substitution. Reproduce the shape (a deeply-indented
    Python diff hunk) and confirm it now matches despite non-uniform
    whitespace-run collapsing on the rendered side."""
    submitted = (
        "@@ -148,6 +148,22 @@ class ObservationTracker:\n"
        "                 self.state = ObservationState.ACTIVE\n"
        "                 clock.candidate_entered_at = None\n"
        "+            elif not observation.terminal_candidate:\n"
        "+                self.state = ObservationState.ACTIVE\n"
    )
    # Approximates the real observed shape: some leading runs collapse to
    # a single \xa0, others partially retain alternating \xa0/space pairs --
    # deliberately non-uniform, matching what was actually captured live.
    rendered = (
        "@@ -148,6 +148,22 @@ class ObservationTracker:\n"
        "\xa0self.state = ObservationState.ACTIVE\n"
        "\xa0clock.candidate_entered_at = None\n"
        "+\xa0\xa0\xa0\xa0elif not observation.terminal_candidate:\n"
        "+\xa0self.state = ObservationState.ACTIVE\n"
    )
    assert len(submitted) != len(rendered)
    assert match_prompt(submitted, rendered)


def test_real_incident_gp44_blank_line_padding_around_fenced_code_block() -> None:
    """GP44 (2026-08-17, req_42f9580ebfcd45d6): a design-consultation prompt
    containing one fenced code block got stuck in submission-proof
    indefinitely -- the gateway's persisted request record never advanced
    past 'running' even though ChatGPT had received and fully, correctly
    answered the real prompt. Reconstructing the exact submitted text and
    the exact observed DOM text and diffing them (after the GP43 fix)
    found only two residual mismatches: ChatGPT's renderer inserts an
    extra blank line immediately before and after a fenced code block's
    rendered content. Reproduce that exact shape."""
    submitted = (
        "before the block:\n"
        "```\n"
        'if x:\n    do_thing()\n'
        "```\n"
        "after the block"
    )
    # ChatGPT's rendering adds a blank line at the open and close of the
    # code block's rendered content -- the fence markers themselves are
    # already stripped by the time DOM text is read.
    rendered = "before the block:\n\nif x:\n    do_thing()\n\nafter the block"
    assert match_prompt(submitted, rendered)


def test_normalize_treats_any_blank_line_run_as_equivalent_to_a_plain_break() -> None:
    """GP44: a plain line break and any run of blank lines around it (one
    blank line, several blank lines) all normalize to a single newline --
    the same "presence, not exact repetition count, is what matters"
    principle GP43 already applies to horizontal whitespace runs. This is
    deliberate: ChatGPT's renderer was observed adding blank-line padding
    non-deterministically, so the exact blank-line count was never a
    reliable signal of the original prompt's structure in the first place."""
    assert normalize_prompt_text("a\n\nb") == normalize_prompt_text("a\nb")
    assert normalize_prompt_text("a\n\n\nb") == normalize_prompt_text("a\nb")
    assert normalize_prompt_text("a\nb") != normalize_prompt_text("ab")


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
