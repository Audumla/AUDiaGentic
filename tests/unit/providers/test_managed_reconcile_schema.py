"""PC07 step 3: drift guard for the generated managed-mcp/managed-hooks schemas.

managed_reconcile_schema.py is the single source of truth for the shared
managed-reconcile envelope; these 4 JSON files under contracts/ are its
generated output, checked in for readability. If this test fails, someone
edited the JSON by hand instead of the generator (or forgot to regenerate).
"""
from __future__ import annotations

import json
from pathlib import Path

from audiagentic.components.providers.contracts import managed_reconcile_schema as gen


def test_generated_schema_files_match_generator() -> None:
    contracts_dir = Path(gen.__file__).resolve().parent
    for filename, builder in gen.GENERATED_SCHEMA_FILES.items():
        on_disk = json.loads((contracts_dir / filename).read_text(encoding="utf-8"))
        assert on_disk == builder(), (
            f"{filename} is out of sync with managed_reconcile_schema.py -- "
            "run `python -m audiagentic.components.providers.contracts."
            "managed_reconcile_schema` to regenerate"
        )
