"""PC07 step 4: drift guard for the generated capability-id taxonomy doc.

taxonomy_doc_generator.py reads _capabilities.yaml directly, so the doc
can't drift from the loader-enforced catalogue mechanics; this test only
guards that someone regenerated after editing the catalogue or the
generator, and that every kind has a curated one-line description.
"""
from __future__ import annotations

from audiagentic.components.providers.descriptors.capability_catalogue import (
    get_catalogue,
)
from audiagentic.components.providers.descriptors.taxonomy_doc_generator import (
    _DOC_PATH,
    KIND_DESCRIPTIONS,
    render_taxonomy_doc,
)


def test_taxonomy_doc_matches_generator() -> None:
    on_disk = _DOC_PATH.read_text(encoding="utf-8")
    assert on_disk == render_taxonomy_doc(), (
        "capability-id-taxonomy.md is out of sync with the generator -- run "
        "`python -m audiagentic.components.providers.descriptors."
        "taxonomy_doc_generator` to regenerate"
    )


def test_every_kind_has_a_description() -> None:
    catalogue = get_catalogue()
    missing = sorted(set(catalogue.kinds_by_id) - set(KIND_DESCRIPTIONS))
    assert missing == [], f"kinds missing a taxonomy doc description: {missing}"


def test_no_stale_descriptions_for_deleted_kinds() -> None:
    catalogue = get_catalogue()
    stale = sorted(set(KIND_DESCRIPTIONS) - set(catalogue.kinds_by_id))
    assert stale == [], f"KIND_DESCRIPTIONS has entries for kinds no longer in the catalogue: {stale}"
