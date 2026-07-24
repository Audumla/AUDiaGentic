#!/usr/bin/env bash
# Clean-room packaging checks (merged install-test + server-smoke + release-test).
# Runs against a wheel-installed package with NO dev toolchain present, proving
# the wheel is self-contained. Each check is independent and reports its own
# PASS/FAIL; the script aggregates the exit code.
set -uo pipefail

rc=0

# Snapshot immutable image areas before launcher/tests run. All expected runtime
# writes belong below HOME or /tmp; changes elsewhere indicate boundary leakage.
python3 - <<'PYEOF' >/tmp/audiagentic-packaging-before.json
import hashlib
import json
from pathlib import Path

roots = (Path("/app"), Path("/root"))
snapshot = {}
for root in roots:
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = str(path.relative_to(root))
        snapshot[f"{root}:{relative}"] = hashlib.sha256(path.read_bytes()).hexdigest()
print(json.dumps(snapshot, sort_keys=True))
PYEOF

echo "::: check 0 — installed package imports without source-tree assistance :::"
if env -u PYTHONPATH -u AUDIAGENTIC_REPO_ROOT python3 -c \
	"import audiagentic; import audiagentic.launcher"; then
	echo "PASS: installed package imports"
else
	echo "FAIL: installed package import failed" >&2
	rc=1
fi

echo "::: check 1 — public console script starts and exposes its contract :::"
if env -u PYTHONPATH -u AUDIAGENTIC_REPO_ROOT audiagentic --help |
	grep -q "component"; then
	echo "PASS: audiagentic --help"
else
	echo "FAIL: public console script did not expose help" >&2
	rc=1
fi

echo "::: check 2 — installed CLI loads descriptors in isolated project :::"
if env -u PYTHONPATH -u AUDIAGENTIC_REPO_ROOT python3 - <<'PYEOF'; then
import json
import os
import subprocess
from pathlib import Path

project = Path("/tmp/audiagentic-cli-project")
project.mkdir(parents=True, exist_ok=True)
env = dict(os.environ)
env.pop("PYTHONPATH", None)
env.pop("AUDIAGENTIC_REPO_ROOT", None)
result = subprocess.run(
    ["audiagentic", "--project", str(project), "component", "list"],
    cwd=project,
    env=env,
    capture_output=True,
    text=True,
    encoding="utf-8",
    timeout=30,
)
assert result.returncode == 0, result.stderr
rows = json.loads(result.stdout)
assert isinstance(rows, list) and any(row["component_id"] == "project" for row in rows)
assert "Traceback" not in result.stderr
PYEOF
	echo "PASS: installed CLI loads packaged component descriptors"
else
	echo "FAIL: installed CLI descriptor load failed" >&2
	rc=1
fi

echo "::: check 3 — invalid public CLI matrix has stable actionable failures :::"
if env -u PYTHONPATH -u AUDIAGENTIC_REPO_ROOT python3 - <<'PYEOF'; then
import os
import subprocess

env = dict(os.environ)
env.pop("PYTHONPATH", None)
env.pop("AUDIAGENTIC_REPO_ROOT", None)
cases = [
    (["audiagentic", "component", "list", "--bad-option"], 2, "unrecognized arguments"),
    (["audiagentic", "unknown-command"], 2, "invalid choice"),
    (["audiagentic", "component"], 2, "required"),
    (["audiagentic", "component", "status", "does-not-exist"], 1, "unknown component"),
]
for command, expected_rc, expected_message in cases:
    result = subprocess.run(
        command, env=env, capture_output=True, text=True,
        encoding="utf-8", timeout=30,
    )
    combined = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == expected_rc, (
        command, result.returncode, result.stdout, result.stderr
    )
    assert expected_message in combined.lower(), (command, combined)
    assert "Traceback" not in combined, (command, combined)
PYEOF
	echo "PASS: invalid CLI matrix fails cleanly"
else
	echo "FAIL: invalid CLI matrix contract failed" >&2
	rc=1
fi

echo "::: check 4 — bootstrap materializes a working harness :::"
if audiagentic bootstrap --target "$AUDIAGENTIC_HOME/harness" &&
	test -f "$AUDIAGENTIC_HOME/harness/cli/node_modules/.bin/pi"; then
	python3 - <<'PYEOF'
import sys
from pathlib import Path
import os
pi_pkg = Path(os.environ['AUDIAGENTIC_HOME']) / 'harness/cli/node_modules/@earendil-works/pi-coding-agent'
nested = pi_pkg / 'node_modules' / '@earendil-works'
if not nested.exists():
    print('PASS: install OK (no nested @earendil-works packages to check)')
    sys.exit(0)
empty = [d.name for d in nested.glob('*') if (d / 'dist').exists() and not any((d / 'dist').iterdir())]
if empty:
    print(f'FAIL: empty dist/ in nested packages: {empty}', file=sys.stderr)
    sys.exit(1)
print('PASS: agent install OK, nested dist/ populated')
PYEOF
	rc=$((rc | $?))
else
	echo "FAIL: agent install did not produce a pi binary" >&2
	rc=1
fi

echo "::: check 5 — MCP servers import / start (server smoke) :::"
python3 /app/tests/docker/_server_smoke.py
rc=$((rc | $?))

echo "::: check 6 — release CLI e2e against wheel-installed package :::"
pytest /app/tests/e2e/cli -q -p no:cacheprovider -m "not opt_in"
rc=$((rc | $?))

echo "::: check 7 — wheel contains required package-data resources :::"
if env -u PYTHONPATH -u AUDIAGENTIC_REPO_ROOT python3 - <<'PYEOF'; then
import sys
from importlib.resources import files

required = [
    ("audiagentic.components.agents", "workflows.yaml"),
    ("audiagentic.components.planning", "workflows.yaml"),
    ("audiagentic.components.agent_jobs", "workflows.yaml"),
]
for pkg, name in required:
    try:
        resource = files(pkg) / name
        content = resource.read_text(encoding="utf-8")
        if not content.strip():
            print(f"FAIL: {pkg}/{name} is empty", file=sys.stderr)
            sys.exit(1)
        print(f"OK: {pkg}/{name}")
    except Exception as e:
        print(f"FAIL: {pkg}/{name}: {e}", file=sys.stderr)
        sys.exit(1)
print("PASS: all required workflow YAMLs present in wheel")
PYEOF
	echo "PASS: wheel contains required package-data"
else
	echo "FAIL: wheel missing required package-data" >&2
	rc=1
fi

echo "::: check 8 — launcher writes remain in disposable container roots :::"
if python3 - <<'PYEOF'; then
import hashlib
import json
from pathlib import Path

before = json.loads(Path("/tmp/audiagentic-packaging-before.json").read_text(encoding="utf-8"))
roots = (Path("/app"), Path("/root"))
after = {}
for root in roots:
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = str(path.relative_to(root))
        after[f"{root}:{relative}"] = hashlib.sha256(path.read_bytes()).hexdigest()
assert after == before, {
    "added": sorted(after.keys() - before.keys()),
    "removed": sorted(before.keys() - after.keys()),
    "changed": sorted(key for key in after.keys() & before.keys() if after[key] != before[key]),
}
PYEOF
	echo "PASS: launcher paths are contained below /tmp"
else
	echo "FAIL: files outside disposable roots changed" >&2
	rc=1
fi

exit $rc
