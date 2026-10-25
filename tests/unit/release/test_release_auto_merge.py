"""Execute the actual github-script snippets against a mocked GitHub API."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="Node required for workflow script execution")


def execute(job, case="ok"):
    workflow = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())
    steps = workflow["jobs"][job]["steps"]
    step = next(s for s in steps if s.get("id") == "release-pr") if job == "release-please" else steps[0]
    harness = r"""
const {script, scenario} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const calls = [], outputs = {};
const pr = {number:44, state:'open', user:{login:'github-actions[bot]'},
  head:{sha:'a'.repeat(40), ref:'release-please--branches--main', repo:{full_name:'Audumla/AUDiaGentic'}},
  base:{ref:'main',sha:'b'.repeat(40)}, labels:[{name:'autorelease: pending'}]};
if(scenario === 'stale') pr.head.sha = 'b'.repeat(40);
if(scenario === 'foreign') pr.head.repo.full_name = 'evil/fork';
if(scenario === 'human') pr.user.login = 'some-user';
if(scenario === 'wrong-base') pr.base.ref = 'other';
if(scenario === 'already-merged') {pr.state='closed'; pr.merged=true;}
if(scenario === 'closed') pr.state='closed';
const github = {rest:{pulls:{
  list: async () => ({data: scenario === 'none' ? [] : scenario === 'ambiguous' ? [pr,pr] : [pr]}),
  get: async () => ({data:pr}), listFiles: ()=>{},
  merge: async args => {calls.push(['merge',args]); return {data:{merged: scenario !== 'merge-failed'}};}
}, repos:{createCommitStatus: async args => {calls.push(['privacy-status',args]);}},
actions:{createWorkflowDispatch: async args => {calls.push(['dispatch',args]);}}},
paginate: async () => [{filename: scenario === 'unexpected-file' ? '.github/workflows/release.yml' : 'pyproject.toml'}]};
const core = {setOutput:(key,value)=>{outputs[key]=value;}};
const context = {repo:{owner:'Audumla',repo:'AUDiaGentic'},ref:'refs/heads/main'};
process.env.RELEASE_PR='44'; process.env.RELEASE_HEAD='a'.repeat(40);
process.env.SOURCE_SHA=scenario === 'invalid-source' ? 'main' : 'c'.repeat(40);
(async()=>{let error=null; try {
  await new (Object.getPrototypeOf(async function(){}).constructor)('github','context','core',script)(github,context,core);
} catch(e){error=e.message;}
process.stdout.write(JSON.stringify({error,calls,outputs}));})();
"""
    result = subprocess.run([NODE, "-e", harness], input=json.dumps({"script": step["with"]["script"], "scenario": case}),
                            text=True, capture_output=True, check=True)
    return json.loads(result.stdout)


def test_generated_pr_selects_exact_head():
    result = execute("release-please")
    assert result["error"] is None
    assert result["outputs"] == {"number": "44", "sha": "a" * 40, "base": "b" * 40}


@pytest.mark.parametrize("case", ["foreign", "human", "unexpected-file", "ambiguous"])
def test_untrusted_release_pr_is_rejected(case):
    result = execute("release-please", case)
    assert result["error"] and not result["outputs"]


def test_no_release_pr_is_a_noop():
    assert execute("release-please", "none")["outputs"] == {}


def test_merge_is_sha_guarded_and_then_dispatches():
    result = execute("merge-release-pr")
    assert result["error"] is None
    assert [call[0] for call in result["calls"]] == ["privacy-status", "merge", "dispatch"]
    assert result["calls"][0][1]["context"] == "privacy"
    assert result["calls"][0][1]["sha"] == "a" * 40
    assert result["calls"][1][1]["sha"] == "a" * 40
    assert result["calls"][2][1]["workflow_id"] == "release.yml"


@pytest.mark.parametrize("case", ["stale", "foreign", "human", "wrong-base", "closed"])
def test_changed_pr_blocks_merge_and_dispatch(case):
    result = execute("merge-release-pr", case)
    assert result["error"] and not result["calls"]


def test_failed_merge_never_dispatches():
    result = execute("merge-release-pr", "merge-failed")
    assert result["error"]
    assert [call[0] for call in result["calls"]] == ["privacy-status", "merge"]


def test_retry_after_merge_dispatches_without_merging_again():
    result = execute("merge-release-pr", "already-merged")
    assert result["error"] is None
    assert [call[0] for call in result["calls"]] == ["dispatch"]


def test_post_publication_dispatch_uses_immutable_source():
    result = execute("dispatch-full-validation")
    assert result["error"] is None
    assert result["calls"][0][1]["workflow_id"] == "ci-full.yml"
    assert result["calls"][0][1]["inputs"] == {"source_ref": "c" * 40}


def test_post_publication_dispatch_rejects_mutable_source():
    result = execute("dispatch-full-validation", "invalid-source")
    assert result["error"] and not result["calls"]
