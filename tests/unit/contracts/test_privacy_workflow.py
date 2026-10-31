"""The required privacy gate also covers bot-created release/ledger PRs."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_privacy_workflow_is_unfiltered_and_uses_trusted_base_policy():
    workflow = yaml.load((ROOT / '.github/workflows/privacy.yml').read_text(), Loader=yaml.BaseLoader)
    assert {'pull_request_target', 'push', 'workflow_call'} <= set(workflow['on'])
    assert workflow['on']['pull_request_target'] == ''
    job = workflow['jobs']['privacy']
    script = next(step['run'] for step in job['steps'] if 'run' in step)
    assert 'git show "$PRIVACY_BASE:tools/privacy_guard.py"' in script
    assert 'git show "$PRIVACY_BASE:tools/privacy_binary_allow.json"' in script
    assert 'python "$scanner" --base "$PRIVACY_BASE"' in script
    assert 'continue-on-error' not in str(workflow)
    status = job['steps'][-1]
    assert 'always()' in status['if']
    assert 'context.payload.pull_request.head.sha' in status['with']['script']
    assert 'Trusted base privacy policy is unavailable' in script


def test_release_and_ledger_pr_statuses_require_real_exact_head_scans():
    workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
    jobs = workflow['jobs']
    gate = jobs['release-pr-privacy']
    assert gate['uses'] == './.github/workflows/privacy.yml'
    assert 'release_head' in gate['with']['source_ref']
    assert 'release_base' in gate['with']['base_sha']
    merge = jobs['merge-release-pr']
    assert 'release-pr-privacy' in merge['needs']
    assert merge['permissions']['statuses'] == 'write'
    script = merge['steps'][0]['with']['script']
    assert script.index('pr.head.sha !== sha') < script.index('createCommitStatus')
    assert script.index('createCommitStatus') < script.index('pulls.merge')
    ledger = jobs['finalize-ledger']
    step = next(s for s in ledger['steps'] if s.get('name') == 'Commit release artifacts')
    script = step['run']
    assert script.index('python tools/privacy_guard.py --base') < script.index('gh pr merge')
    assert 'context=privacy' in script


# The repository ruleset on the default branch requires these status contexts. Bot-created PRs do not
# trigger CI, so release automation must report each one itself, on the exact commit it validated.
REQUIRED_CONTEXTS = ("privacy", "tests")
LEDGER_ARTIFACTS = (
    "docs/releases/LEDGER.ndjson", "docs/releases/CURRENT_RELEASE_LEDGER.ndjson", "docs/releases/RELEASE_NOTES.md",
    "docs/releases/VERSION_HISTORY.md", "docs/releases/CURRENT_RELEASE.md",
)


def test_release_pr_reports_every_required_context_on_the_validated_head_before_merging():
    workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
    merge = workflow['jobs']['merge-release-pr']
    assert {'release-pr-tests', 'release-pr-privacy'} <= set(merge['needs'])  # only runs after both gates passed
    script = merge['steps'][0]['with']['script']
    head_check = script.index('pr.head.sha !== sha')
    for context in REQUIRED_CONTEXTS:
        status = script.index(f"context: '{context}'")
        assert head_check < status < script.index('pulls.merge'), context


def test_ledger_pr_reports_every_required_context_only_after_proving_it_is_generated_artifacts_only():
    workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
    step = next(s for s in workflow['jobs']['finalize-ledger']['steps'] if s.get('name') == 'Commit release artifacts')
    script = step['run']
    for artifact in LEDGER_ARTIFACTS:  # the same five files are staged and allow-listed
        assert script.count(artifact) >= 2, artifact
    guard = script.index('unexpected=$(')
    assert script.index('python tools/privacy_guard.py --base') < guard < script.index('git push')
    assert 'exit 1' in script[guard:script.index('git push')]
    for context in REQUIRED_CONTEXTS:
        assert guard < script.index(f'context={context}') < script.index('gh pr merge'), context
