#!/usr/bin/env bash
# Clean-room packaging checks (merged install-test + server-smoke + release-test).
# Runs against a wheel-installed package with NO dev toolchain present, proving
# the wheel is self-contained. Each check is independent and reports its own
# PASS/FAIL; the script aggregates the exit code.
set -uo pipefail

export AUDIAGENTIC_REPO_ROOT=/app
rc=0

echo "::: check 1 — agent install materializes a working harness :::"
if audiagentic install --target /root/.audiagentic/harness \
    && test -f /root/.audiagentic/harness/cli/node_modules/.bin/pi; then
    python3 - <<'PYEOF'
import sys
from pathlib import Path
pi_pkg = Path('/root/.audiagentic/harness/cli/node_modules/@earendil-works/pi-coding-agent')
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

echo "::: check 2 — MCP servers import / start (server smoke) :::"
python3 /app/tests/docker/_server_smoke.py
rc=$((rc | $?))

echo "::: check 3 — release CLI e2e against wheel-installed package :::"
pytest tests/e2e/cli -q
rc=$((rc | $?))

exit $rc
