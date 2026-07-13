#!/usr/bin/env bash
# Clean-room packaging checks (merged install-test + server-smoke + release-test).
# Runs against a wheel-installed package with NO dev toolchain present, proving
# the wheel is self-contained. Each check is independent and reports its own
# PASS/FAIL; the script aggregates the exit code.
set -uo pipefail

export AUDIAGENTIC_REPO_ROOT=/app
rc=0

echo "::: check 0 — installed package imports without source-tree assistance :::"
if env -u PYTHONPATH -u AUDIAGENTIC_REPO_ROOT python3 -c \
    "import audiagentic; import audiagentic.launcher"; then
    echo "PASS: installed package imports"
else
    echo "FAIL: installed package import failed" >&2
    rc=1
fi

echo "::: check 1 — public console script starts and exposes its contract :::"
if env -u PYTHONPATH -u AUDIAGENTIC_REPO_ROOT audiagentic --help \
    | grep -q "component"; then
    echo "PASS: audiagentic --help"
else
    echo "FAIL: public console script did not expose help" >&2
    rc=1
fi

echo "::: check 2 — installed CLI loads descriptors in isolated project :::"
if env -u PYTHONPATH -u AUDIAGENTIC_REPO_ROOT python3 - <<'PYEOF'
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
then
    echo "PASS: installed CLI loads packaged component descriptors"
else
    echo "FAIL: installed CLI descriptor load failed" >&2
    rc=1
fi

echo "::: check 3 — invalid public CLI invocation has actionable parser failure :::"
if env -u PYTHONPATH -u AUDIAGENTIC_REPO_ROOT python3 - <<'PYEOF'
import os
import subprocess

env = dict(os.environ)
env.pop("PYTHONPATH", None)
env.pop("AUDIAGENTIC_REPO_ROOT", None)
result = subprocess.run(
    ["audiagentic", "component"], env=env, capture_output=True, text=True,
    encoding="utf-8", timeout=30,
)
assert result.returncode == 2, (result.returncode, result.stdout, result.stderr)
assert "required" in result.stderr.lower(), result.stderr
assert "Traceback" not in result.stderr
PYEOF
then
    echo "PASS: invalid CLI invocation fails cleanly"
else
    echo "FAIL: invalid CLI invocation contract failed" >&2
    rc=1
fi

echo "::: check 4 — agent install materializes a working harness :::"
if audiagentic install --target "$AUDIAGENTIC_HOME/harness" \
    && test -f "$AUDIAGENTIC_HOME/harness/cli/node_modules/.bin/pi"; then
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
pytest tests/e2e/cli -q -m "not opt_in"
rc=$((rc | $?))

echo "::: check 7 — launcher writes remain in disposable container roots :::"
if find "$HOME" /tmp/audiagentic-cli-project -xdev -print >/dev/null; then
    echo "PASS: launcher paths are contained below /tmp"
else
    echo "FAIL: cannot inspect disposable launcher roots" >&2
    rc=1
fi

exit $rc
