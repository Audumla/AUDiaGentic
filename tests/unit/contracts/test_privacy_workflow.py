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
