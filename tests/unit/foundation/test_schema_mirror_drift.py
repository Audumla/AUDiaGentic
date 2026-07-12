"""Drift test for component-owned schemas mirrored into foundation/contracts/schemas/.

Ensures every mirrored schema in foundation/contracts/schemas/ is byte-identical
to its authoritative copy under components/<component>/contracts/.  Foundation-native
schemas (no matching component copy) are exempt.
"""
from pathlib import Path

FINDINGS = []


def test_schema_mirror_drift():
    root = Path(__file__).resolve().parents[3] / "src" / "audiagentic"

    foundation_schemas_dir = root / "foundation" / "contracts" / "schemas"
    component_contracts_dirs: list[Path] = []

    components_dir = root / "components"
    if components_dir.is_dir():
        for entry in components_dir.iterdir():
            contracts_subdir = entry / "contracts"
            if contracts_subdir.is_dir():
                component_contracts_dirs.append(contracts_subdir)

    for schema_path in foundation_schemas_dir.glob("*.json"):
        filename = schema_path.name
        authoritative: Path | None = None

        for comp_contracts_dir in component_contracts_dirs:
            candidate = comp_contracts_dir / filename
            if candidate.exists():
                if authoritative is not None:
                    msg = (
                        f"{filename}: multiple component copies found "
                        f"({authoritative} and {candidate}); exactly one or none expected."
                    )
                    FINDINGS.append(msg)
                authoritative = candidate
                break

        if authoritative is None:
            continue

        mirror_bytes = schema_path.read_bytes()
        auth_bytes = authoritative.read_bytes()
        if mirror_bytes != auth_bytes:
            msg = (
                f"{filename}: foundation mirror differs from authoritative copy. "
                f"Mirror: {schema_path}\n"
                f"Authoritative (to re-sync from): {authoritative}"
            )
            FINDINGS.append(msg)

    if FINDINGS:
        raise AssertionError(
            "Schema mirror drift detected:\n\n" + "\n\n".join(FINDINGS)
        )
