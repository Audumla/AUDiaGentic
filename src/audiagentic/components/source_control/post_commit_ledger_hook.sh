# audiagentic-ledger-stamp
# Installed by AUDiaGentic source-control component when agent-ledger is present.
# Stamps ledger events with the commit SHA for any files that intersect.
# Errors are shown, not suppressed: git ignores a post-commit exit code, so a
# broken hook cannot fail the commit -- but a silent one hides its own breakage.
python -c "
from pathlib import Path
from audiagentic.components.source_control.git_commits import stamp_ledger_for_commit
stamp_ledger_for_commit(Path('.').resolve())
" || true
