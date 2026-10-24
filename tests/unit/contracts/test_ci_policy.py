"""Coverage, isolation, provenance and workflow gates for tiered CI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.ci.audit import audit
from tests.ci.package_smoke import distribution_hashes
from tests.ci.policy import BROWSER_MODULES, CRITICAL, fast_paths, partition
from tests.ci.run import changed_paths

ROOT = Path(__file__).resolve().parents[3]
SHA = "a" * 40


def nodes():
    return [
        {"nodeid": "tests/a.py::test_a", "markers": []},
        {"nodeid": "tests/b.py::test_b", "markers": []},
        {"nodeid": "tests/s.py::test_serial", "markers": ["no_parallel"]},
        {"nodeid": "tests/s.py::test_neighbor", "markers": []},
        {"nodeid": sorted(BROWSER_MODULES)[0] + "::test_browser", "markers": []},
    ]


def test_partition_is_deterministic_complete_and_keeps_serial_modules_together():
    plan = partition(nodes(), 2)
    assert plan == partition(list(reversed(nodes())), 2)
    assert plan["serial"] == ["tests/s.py"]
    assert plan["browser"] == [sorted(BROWSER_MODULES)[0]]
    assigned = [module for modules in plan.values() for module in modules]
    assert len(assigned) == len(set(assigned)) == 4


@pytest.mark.parametrize("bad", [[], nodes() + nodes()[:1]])
def test_collection_fails_closed_on_empty_or_duplicate_ids(bad):
    with pytest.raises(ValueError):
        partition(bad, 2)


def test_empty_shards_are_rejected_at_inventory_time():
    with pytest.raises(ValueError, match="nonempty shards"):
        partition(nodes(), 3)


def test_fast_coverage_is_mandatory_and_overlapping_paths_are_deduplicated(tmp_path):
    with pytest.raises(ValueError, match="mandatory"):
        fast_paths(tmp_path, [])
    for name in CRITICAL:
        path = tmp_path / name
        if name.endswith(".py"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        else:
            path.mkdir(parents=True, exist_ok=True)
    paths = fast_paths(tmp_path, ["src/audiagentic/components/agents/api.py"])
    assert "tests/unit/agents" in paths
    assert not any(path.startswith("tests/unit/agents/") for path in paths)
    assert set(paths).isdisjoint(BROWSER_MODULES)


@pytest.mark.parametrize("base", ["--output=/tmp/x", "main;exit", "refs/heads/main"])
def test_diff_selection_only_accepts_immutable_commit_ids(base):
    with pytest.raises(ValueError, match="immutable"):
        changed_paths(base)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def evidence_tree(root):
    collection = nodes()
    lanes = partition(collection, 2)
    for role in ["inventory", *lanes]:
        write_json(
            root / role / "plan.json",
            {"role": role, "source_sha": SHA, "nodes": collection, "lanes": lanes},
        )
        if role != "inventory":
            results = {
                node["nodeid"]: {"call": {"outcome": "passed", "seconds": 0.1}}
                for node in collection
                if node["nodeid"].split("::", 1)[0] in lanes[role]
            }
            write_json(
                root / role / f"{role}.json",
                {"source_sha": SHA, "results": results, "exitstatus": 0},
            )


def test_full_audit_proves_exact_once_coverage(tmp_path):
    evidence_tree(tmp_path)
    assert audit(tmp_path, SHA, 2)["tests_accounted_for"] == 5


@pytest.mark.parametrize(
    "mutation", ["missing-role", "foreign-sha", "missing-test", "duplicate-worker", "failed-worker"]
)
def test_full_audit_rejects_incomplete_stale_duplicated_or_failed_evidence(tmp_path, mutation):
    evidence_tree(tmp_path)
    report_path = tmp_path / "shard-0" / "shard-0.json"
    report = json.loads(report_path.read_text())
    if mutation == "missing-role":
        (tmp_path / "browser" / "plan.json").unlink()
    elif mutation == "foreign-sha":
        report["source_sha"] = "b" * 40
    elif mutation == "missing-test":
        report["results"] = {}
    elif mutation == "duplicate-worker":
        write_json(report_path.with_name("shard-0-gw0.json"), report)
        write_json(report_path.with_name("shard-0-gw1.json"), report)
    else:
        report["exitstatus"] = 1
    write_json(report_path, report)
    with pytest.raises(ValueError):
        audit(tmp_path, SHA, 2)


def test_evidence_plugin_records_tests_without_raw_logs(tmp_path):
    sample = tmp_path / "test_sample.py"
    sample.write_text(
        'import pytest\ndef test_one():\n print("do-not-store-payload")\n assert True\n@pytest.mark.skip\ndef test_two(): pass\n',
        encoding="utf-8",
    )
    report = tmp_path / "proof.json"
    env = {**os.environ, "PYTHONPATH": str(ROOT), "CI_SOURCE_SHA": SHA, "PYTEST_XDIST_WORKER": "inherited-not-a-worker"}
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(sample),
            "--rootdir",
            str(tmp_path),
            "-o",
            "addopts=",
            "-p",
            "tests.ci.evidence",
            "--ci-evidence",
            str(report),
            "-q",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    proof = json.loads(report.read_text())
    assert proof["source_sha"] == SHA
    assert len(proof["nodes"]) == len(proof["results"]) == 2
    assert "do-not-store-payload" not in report.read_text()


def test_package_artifact_hashes_require_exact_distribution_pair(tmp_path):
    with pytest.raises(ValueError):
        distribution_hashes(tmp_path)
    (tmp_path / "audiagentic-1.2.3-py3-none-any.whl").write_bytes(b"wheel")
    (tmp_path / "audiagentic-1.2.3.tar.gz").write_bytes(b"sdist")
    before = distribution_hashes(tmp_path)
    (tmp_path / "audiagentic-1.2.3.tar.gz").write_bytes(b"modified")
    assert distribution_hashes(tmp_path) != before


def load_workflow(name):
    return yaml.load((ROOT / ".github/workflows" / name).read_text(), Loader=yaml.BaseLoader)


def test_release_requires_fast_finalized_source_and_installed_distribution_proof():
    jobs = load_workflow("release.yml")["jobs"]
    assert "release-tests" in jobs["build-and-publish"]["needs"]
    assert jobs["release-tests"]["uses"] == "./.github/workflows/ci-tests.yml"
    assert "finalized_sha" in jobs["release-tests"]["with"]["source_ref"]
    steps = jobs["build-and-publish"]["steps"]
    proof = next(
        index for index, step in enumerate(steps) if "package_smoke.py" in step.get("run", "")
    )
    publish = next(
        index
        for index, step in enumerate(steps)
        if "gh-action-pypi-publish" in step.get("uses", "")
    )
    assert proof < publish


def test_full_is_background_scheduled_and_has_all_coverage_roles():
    config = load_workflow("ci-full.yml")
    assert {"push", "schedule", "release", "workflow_dispatch"} <= set(config["on"])
    jobs = config["jobs"]
    assert jobs["suite"]["strategy"]["matrix"]["lane"] == [
        "shard-0",
        "shard-1",
        "shard-2",
        "shard-3",
        "serial",
    ]
    assert set(jobs["coverage-audit"]["needs"]) == {"inventory", "suite", "browser"}
    assert "ci-full" in jobs["inventory"]["if"]
    assert not any("docker" in name for name in load_workflow("ci-tests.yml")["jobs"])
