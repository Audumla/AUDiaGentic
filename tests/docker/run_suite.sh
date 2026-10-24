#!/usr/bin/env bash
# One coverage policy for local and GitHub full-suite runs.
set -euo pipefail
python -m tests.ci.run --tier full --lane "${CI_LANE:-all}" \
  --shards "${CI_SHARDS:-1}" --index "${CI_SHARD_INDEX:-0}" \
  --workers "${AUDIAGENTIC_XDIST_WORKERS:-2}" --results "${CI_RESULTS:-.ci-results}"
