"""Regression coverage for noncanonical planning audit sections."""

from __future__ import annotations

from audiagentic.components.planning import planning_api, planning_paths


def test_update_item_preserves_custom_audits_before_and_between_standard_sections(
    tmp_path,
) -> None:
    planning_api.create_item(
        tmp_path,
        {
            "id": "PRBE29",
            "plan": "test-plan",
            "title": "Persistent F16 shadow",
            "created-by": "agent",
            "validation": "native fixture and KLD",
            "acceptance_criteria": "compare on matching hardware",
        },
    )
    item_path = planning_paths.plans_active_dir(tmp_path) / "test-plan" / "PRBE29.md"
    original = item_path.read_text(encoding="utf-8")

    first_audit = (
        "## 2026-10-09 PRBE28 ownership reconciliation\n\n"
        "This exact source review predates the standard Description section.\n"
        "- One shadow owner; no duplicate allocator.\n"
        "- Keep original quantized source intact.\n"
    )
    second_audit = (
        "## 2026-10-10 BCOP126: load-complete shadow admission\n\n"
        "Retain these unsummarized acceptance details across updates.\n"
        "### Negative hardware checks\n\n"
        "- An undrained async upload must refuse publication.\n"
        "- A partial overwrite must invalidate the shadow.\n\n"
        "~~~cpp\n"
        "// A fenced heading must stay inside this custom section.\n"
        "## not a section\n"
        "~~~\n"
    )

    assert original.count("## Description") == 1
    assert original.count("## Validation") == 1
    item_path.write_text(
        original.replace("## Description", first_audit + "\n## Description", 1).replace(
            "## Validation", second_audit + "\n## Validation", 1
        ),
        encoding="utf-8",
    )

    planning_api.create_review(
        tmp_path,
        {"review-of": "PRBE29", "title": "Keep provenance"},
    )
    for number in range(3):
        planning_api.update_item(
            tmp_path,
            "PRBE29",
            {
                "acceptance_criteria": f"new gate {number}",
                "notes": f"evaluation {number}",
            },
            append=["acceptance_criteria", "notes"],
        )

    updated = item_path.read_text(encoding="utf-8")
    for audit in (first_audit.strip(), second_audit.strip()):
        assert audit in updated
    assert updated.count("## 2026-10-09 PRBE28 ownership reconciliation") == 1
    assert updated.count("## 2026-10-10 BCOP126: load-complete shadow admission") == 1
    assert updated.count("## not a section") == 1
    assert "## Reviews" in updated
    assert "## Change Log" in updated

    parsed = planning_api.get_item(tmp_path, "PRBE29")
    assert parsed["2026_10_09_prbe28_ownership_reconciliation"].startswith(
        "This exact source review"
    )
    assert "undrained async upload" in parsed[
        "2026_10_10_bcop126_load_complete_shadow_admission"
    ]
    assert parsed["validation"] == "native fixture and KLD"
    assert "new gate 2" in parsed["acceptance_criteria"]
