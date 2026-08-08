"""Test parse_sections and parse_custom_headings with markdown-it-py."""

from __future__ import annotations

from audiagentic.foundation.workflow.frontmatter import (
    parse_custom_headings,
    parse_sections,
)

_HEADING_MAP = {"Description": "description", "Steps": "steps", "Notes": "notes"}


def test_parse_sections_basic_h2_only() -> None:
    """Only h2 headings create fields; h3+ stays embedded in parent."""
    body = (
        "# Title\n"
        "\n"
        "## Description\n"
        "\n"
        "Content.\n"
        "\n"
        "### Sub-step A\n"
        "\n"
        "Sub-content A.\n"
        "\n"
        "## Steps\n"
        "\n"
        "Step 1.\n"
    )

    result = parse_sections(body, _HEADING_MAP)
    assert result["title"] == "Title"
    assert "### Sub-step A" in result["description"], "h3 content should stay in parent field"
    assert "Sub-content A." in result["description"]
    assert result["steps"] == "Step 1."
    # No spurious field from h3
    assert "sub_step_a" not in result


def test_parse_sections_h2_inside_code_block_ignored() -> None:
    """## inside a fenced code block should NOT create a field."""
    body = (
        "# Title\n"
        "\n"
        "## Description\n"
        "\n"
        "Content with code:\n"
        "\n"
        "```\n"
        "## This is in a code block\n"
        "Should be ignored.\n"
        "```\n"
        "\n"
        "More content.\n"
        "\n"
        "## Steps\n"
        "\n"
        "Step 1.\n"
    )

    result = parse_sections(body, _HEADING_MAP)
    assert result["description"] is not None
    # The code block heading should NOT appear as a field
    assert "this_is_in_a_code_block" not in result
    # Code block content stays in parent
    assert "## This is in a code block" in result["description"]


def test_parse_sections_custom_heading_not_spurious_from_h2() -> None:
    """An h2 heading that is NOT a known section should still be a field,
    but it's not a bug — the user wrote ## and we respect that. The fix
    is that h3+ does NOT get promoted to its own field."""
    body = (
        "# Title\n"
        "\n"
        "## Description\n"
        "\n"
        "Content.\n"
        "\n"
        "## Custom Section\n"
        "\n"
        "Custom content.\n"
        "\n"
        "## Notes\n"
        "\n"
        "A note.\n"
    )

    result = parse_sections(body, _HEADING_MAP)
    assert result["custom_section"] == "Custom content."


def test_parse_custom_headings_only_h2() -> None:
    """h3+ headings should not appear as custom headings."""
    body = (
        "# Title\n"
        "\n"
        "## Description\n"
        "\n"
        "Content.\n"
        "\n"
        "### Sub-step A\n"
        "\n"
        "Sub-content.\n"
        "\n"
        "## Custom Section\n"
        "\n"
        "Custom.\n"
    )

    result = parse_custom_headings(body, _HEADING_MAP)
    assert "custom_section" in result
    # h3 should NOT appear as a custom heading
    assert "sub_step_a" not in result


def test_parse_sections_h4_inside_h2_stays_embedded() -> None:
    """h4 headings are also embedded, not promoted."""
    body = "# Title\n\n## Steps\n\nStep 1.\n\n#### Step 1 Detail\n\nDetail about step 1.\n"

    result = parse_sections(body, _HEADING_MAP)
    assert "Step 1." in result["steps"]
    assert "#### Step 1 Detail" in result["steps"], "h4 content should stay embedded"
    assert "step_1_detail" not in result


def test_parse_sections_nested_code_fences() -> None:
    """Multiple code blocks don't interfere with section parsing."""
    body = (
        "# Title\n"
        "\n"
        "## Description\n"
        "\n"
        "First block:\n"
        "\n"
        "```python\n"
        "# not a heading\n"
        "def foo():\n"
        "```\n"
        "\n"
        "Second block:\n"
        "\n"
        "```markdown\n"
        "## Also not a heading\n"
        "```\n"
        "\n"
        "## Steps\n"
        "\n"
        "Step 1.\n"
    )

    result = parse_sections(body, _HEADING_MAP)
    assert "also_not_a_heading" not in result
    assert "```python" in result["description"]
    assert "```markdown" in result["description"]
    assert result["steps"] == "Step 1."


def test_parse_custom_headings_h3_not_custom() -> None:
    """h3 headings within a section are not treated as custom sections."""
    body = (
        "# Title\n"
        "\n"
        "## Description\n"
        "\n"
        "Content.\n"
        "\n"
        "### Implementation Details\n"
        "\n"
        "Details here.\n"
        "\n"
        "## Steps\n"
        "\n"
        "Step 1.\n"
    )

    result = parse_custom_headings(body, _HEADING_MAP)
    # Only known sections should be absent; no custom headings at all
    assert result == {}


def test_parse_sections_unknown_h2_is_custom_field() -> None:
    """An h2 heading not in the map still creates a field (not an error)."""
    body = (
        "# Title\n"
        "\n"
        "## Description\n"
        "\n"
        "Content.\n"
        "\n"
        "## Additional Context\n"
        "\n"
        "Extra info.\n"
        "\n"
        "## Steps\n"
        "\n"
        "Step 1.\n"
    )

    result = parse_sections(body, _HEADING_MAP)
    assert result["additional_context"] == "Extra info."
