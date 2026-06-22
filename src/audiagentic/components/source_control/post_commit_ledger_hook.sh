# audiagentic-ledger-stamp
# Installed by AUDiaGentic source-control component when agent-ledger is present.
# Stamps ledger fragments with the commit SHA for any files that intersect.
python -c "
from pathlib import Path
from audiagentic.components.source_control.git_commits import stamp_fragments_for_commit
stamp_fragments_for_commit(Path('.').resolve())
" 2>/dev/null || true

