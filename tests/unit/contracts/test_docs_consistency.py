from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OWNERSHIP_FILE = ROOT / "docs" / "specifications" / "architecture" / "18_File_Ownership_Matrix.md"
GLOSSARY_FILE = ROOT / "docs" / "specifications" / "architecture" / "19_Glossary.md"


def _parse_ownership_rows(text: str) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        if line.strip().startswith("|---"):
            continue
        cols = [col.strip() for col in line.strip().strip("|").split("|")]
        if not cols or cols[0].lower() == "path":
            continue
        if len(cols) >= 2:
            rows.append((cols[0], cols[1]))
    return rows


def _parse_glossary_terms(text: str) -> list[str]:
    terms: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("- **"):
            parts = line.split("**")
            if len(parts) >= 3:
                term = parts[1].strip()
                if term:
                    terms.append(term)
    return terms


def test_ownership_matrix_has_unique_paths() -> None:
    rows = _parse_ownership_rows(OWNERSHIP_FILE.read_text(encoding="utf-8"))
    paths = [row[0] for row in rows]
    assert len(paths) == len(set(paths))


def test_glossary_terms_unique_and_defined() -> None:
    text = GLOSSARY_FILE.read_text(encoding="utf-8")
    terms = _parse_glossary_terms(text)
    assert terms
    assert len(terms) == len(set(terms))
    for term in terms:
        assert term


def test_docs_parsing_does_not_mutate_files() -> None:
    ownership_before = OWNERSHIP_FILE.read_text(encoding="utf-8")
    glossary_before = GLOSSARY_FILE.read_text(encoding="utf-8")
    _ = _parse_ownership_rows(ownership_before)
    _ = _parse_glossary_terms(glossary_before)
    assert OWNERSHIP_FILE.read_text(encoding="utf-8") == ownership_before
    assert GLOSSARY_FILE.read_text(encoding="utf-8") == glossary_before
