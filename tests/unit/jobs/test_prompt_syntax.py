from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src"
for path in (str(ROOT), str(SRC)):
    if path not in sys.path:
        sys.path.insert(0, path)

from audiagentic.execution.jobs.prompt_syntax import load_canonical_tags
from audiagentic.execution.jobs.prompt_syntax import load_no_body_required_tags
from audiagentic.execution.jobs.prompt_syntax import load_prompt_syntax
from audiagentic.execution.jobs.prompt_syntax import load_review_tag


def test_load_canonical_tags_uses_custom_syntax_values() -> None:
    syntax = {
        "canonical-tags": ["ag-design", "ag-check"],
        "review-tag": "ag-check",
        "no-body-required-tags": ["ag-check"],
    }

    assert load_canonical_tags(syntax) == {"ag-design", "ag-check"}
    assert load_review_tag(syntax) == "ag-check"
    assert load_no_body_required_tags(syntax) == {"ag-check"}


def test_load_prompt_syntax_defaults_include_opencode_aliases(tmp_path: Path) -> None:
    syntax = load_prompt_syntax(tmp_path, profile_name=None)

    assert syntax["provider-aliases"]["opencode"] == "opencode"
    assert syntax["provider-aliases"]["opc"] == "opencode"
