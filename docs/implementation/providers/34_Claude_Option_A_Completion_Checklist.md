# Claude Option A Completion Checklist — PKT-PRV-033

This checklist provides the exact step-by-step work needed to complete Option A (wrapper baseline)
so Option B (native hooks) can begin immediately.

## Files to Create

### 1. `.claude/skills/ag-plan/SKILL.md`

```markdown
# plan skill

Use this skill for canonical `@plan` launches.

Trigger:
- first non-empty line resolves to `plan`

Do:
- produce a concise implementation or review plan
- preserve the normalized request envelope

Do not:
- start implementation work
- redefine the canonical grammar
```

**Task:** Create this file at `h:\development\projects\AUDia\AUDiaGentic\.claude\skills\plan\SKILL.md`

---

### 2. `.claude/skills/ag-implement/SKILL.md`

```markdown
# implement skill

Use this skill for canonical `@implement` launches.

Trigger:
- first non-empty line resolves to `implement`

Do:
- write code, tests, and documentation
- preserve the normalized request envelope
- follow packet build steps deterministically

Do not:
- skip tests or validation
- redefine the canonical grammar
```

**Task:** Create this file at `h:\development\projects\AUDia\AUDiaGentic\.claude\skills\implement\SKILL.md`

---

### 3. `.claude/skills/ag-review/SKILL.md`

```markdown
# review skill

Use this skill for canonical `@review` launches.

Trigger:
- first non-empty line resolves to `review`

Do:
- perform read-focused validation and completeness review
- identify blockers, missing tests, and contract mismatches
- preserve the review bundle and approval flow
- produce a deterministic review report

Do not:
- add new implementation work unless explicitly asked
- broaden review into feature scope changes
- mutate tracked docs without approval
```

**Task:** Create this file at `h:\development\projects\AUDia\AUDiaGentic\.claude\skills\review\SKILL.md`

---

### 4. `.claude/skills/ag-audit/SKILL.md`

```markdown
# audit skill

Use this skill for canonical `@audit` launches.

Trigger:
- first non-empty line resolves to `audit`

Do:
- perform deterministic audit of build state, dependencies, and contracts
- produce audit summary with findings
- identify risk or drift from locked contracts

Do not:
- make changes based on audit findings without explicit approval
- redefine the canonical grammar
```

**Task:** Create this file at `h:\development\projects\AUDia\AUDiaGentic\.claude\skills\audit\SKILL.md`

---

### 5. `.claude/skills/ag-check-in-prep/SKILL.md`

```markdown
# check-in-prep skill

Use this skill for canonical `@check-in-prep` launches.

Trigger:
- first non-empty line resolves to `check-in-prep`

Do:
- prepare release artifacts, audit summaries, and check-in notes
- ensure current-release and audit documents are synchronized
- produce deterministic snapshot of work completed

Do not:
- merge or commit changes without explicit approval
- redefine the canonical grammar
```

**Task:** Create this file at `h:\development\projects\AUDia\AUDiaGentic\.claude\skills\check-in-prep\SKILL.md`

---

## Code to Update

### 6. Update `tools/claude_prompt_trigger_bridge.py`

Add the following after the imports (around line 13):

```python
from pathlib import Path

REQUIRED_ASSETS = (
    Path("CLAUDE.md"),
    Path(".claude/rules/prompt-tags.md"),
    Path(".claude/rules/review-policy.md"),
    Path(".claude/skills/ag-plan/SKILL.md"),
    Path(".claude/skills/ag-implement/SKILL.md"),
    Path(".claude/skills/ag-review/SKILL.md"),
    Path(".claude/skills/ag-audit/SKILL.md"),
    Path(".claude/skills/ag-check-in-prep/SKILL.md"),
)


def _missing_assets(project_root: Path) -> list[str]:
    """Check for required Claude assets before launching."""
    missing: list[str] = []
    for relative_path in REQUIRED_ASSETS:
        if not (project_root / relative_path).exists():
            missing.append(str(relative_path))
    return missing
```

Then update the `if __name__ == "__main__":` block to add preflight validation:

```python
if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    
    project_root = Path(".").resolve()
    missing = _missing_assets(project_root)
    if missing:
        print(
            json.dumps(
                {
                    "status": "error",
                    "kind": "validation",
                    "message": "missing Claude prompt-calling assets",
                    "missing": missing,
                    "project-root": str(project_root),
                },
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(2)
    
    raise SystemExit(run(["--provider-id", "claude", *sys.argv[1:]]))
```

**Task:** Update `tools/claude_prompt_trigger_bridge.py` with preflight validation logic

---

## Tests to Add

### 7. Add missing-assets validation test

File: `tests/integration/providers/test_claude_prompt_trigger_bridge.py`

Add this test function:

```python
def test_claude_prompt_trigger_bridge_missing_assets_returns_validation_error(tmp_path: Path) -> None:
    """Verify that missing Claude assets trigger validation error before launch."""
    sandbox = sandbox_helper.create(tmp_path, "claude-prompt-trigger-missing-assets")
    try:
        _write_project_and_provider_config(sandbox)
        
        # Intentionally don't create .claude/skills directory
        # This simulates the missing assets condition
        
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "claude_prompt_trigger_bridge.py"),
                "--project-root",
                str(sandbox.repo),
            ],
            cwd=ROOT,
            input="@plan target=packet:PKT-JOB-008\nContinue implementing.\n",
            capture_output=True,
            text=True,
            check=False,
        )
        
        assert result.returncode == 2, result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["kind"] == "validation"
        assert "missing" in payload
        assert any("SKILL.md" in m for m in payload["missing"])
    finally:
        sandbox.cleanup()
```

**Task:** Add this test to the Claude bridge test suite

---

## Verification Steps

### 8. Run all tests

```bash
pytest tests/integration/providers/test_claude_prompt_trigger_bridge.py -v
```

Expected results:
- ✅ `test_claude_prompt_trigger_bridge_script_launches_job` — PASS (existing)
- ✅ `test_claude_prompt_trigger_bridge_missing_assets_returns_validation_error` — PASS (new)

**Task:** Verify both tests pass

---

### 9. Manual smoke test

```bash
cd h:\development\projects\AUDia\AUDiaGentic

# Test with assets present
python tools/claude_prompt_trigger_bridge.py --project-root . <<EOF
@plan target=packet:PKT-PRV-033
Review the implementation status.
EOF
```

Expected: Returns JSON with `"status": "created"` and job details.

**Task:** Run manual smoke test with assets present

---

### 10. Manual error test

```bash
# Temporarily remove a skill file
mv .claude/skills/ag-plan/SKILL.md .claude/skills/ag-plan/SKILL.md.bak

python tools/claude_prompt_trigger_bridge.py --project-root . <<EOF
@plan target=packet:PKT-PRV-033
This should fail.
EOF

# Should return error with status "error", kind "validation", missing assets list
# Restore the file
mv .claude/skills/ag-plan/SKILL.md.bak .claude/skills/ag-plan/SKILL.md
```

Expected: Returns JSON with `"status": "error"`, `"kind": "validation"`, lists missing file.

**Task:** Run manual error test and verify validation works

---

## Build Registry Update

### 11. Update build registry

File: `docs/implementation/31_Build_Status_and_Work_Registry.md`

Change PKT-PRV-033 status from `READY_FOR_REVIEW` to `VERIFIED` once all tests pass.

**Task:** Update registry after verification

---

## Acceptance Criteria Checklist

- [ ] `.claude/skills/` directory exists with 5 SKILL.md files
- [ ] `tools/claude_prompt_trigger_bridge.py` has REQUIRED_ASSETS check
- [ ] Preflight validation returns structured JSON error when assets missing
- [ ] `test_claude_prompt_trigger_bridge_script_launches_job` passes
- [ ] `test_claude_prompt_trigger_bridge_missing_assets_returns_validation_error` passes
- [ ] Manual smoke test with assets present succeeds
- [ ] Manual error test shows validation error correctly
- [ ] All other Claude-related tests still pass
- [ ] PKT-PRV-033 status updated to VERIFIED in build registry
- [ ] Option B can now begin immediately (PKT-PRV-055)

---

## Time Estimate

- File creation: ~5 min (5 skill files, copy/paste)
- Code updates: ~10 min (wrapper bridge changes)
- Test writing and running: ~15 min (new test + smoke tests)
- **Total: ~30 minutes**

---

## Next: Option B Starts Here

Once Option A is VERIFIED:
1. PKT-PRV-055 becomes ready to start
2. Use the detailed Option B implementation guide to wire hooks
3. `.claude/settings.json` hook configuration immediately follows
