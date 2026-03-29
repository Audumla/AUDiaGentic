"""Glossary terms used across contracts."""
from __future__ import annotations

GLOSSARY = {
    "packet": "one bounded implementation or execution unit used by jobs and plans",
    "tracked-docs": "git-managed files under docs/ and selected .audiagentic/*.yaml",
    "runtime": "git-ignored operational state under .audiagentic/runtime/",
    "release-artifact": "packaged install/update bundle for AUDiaGentic",
    "job-artifact": "runtime output produced by a job",
    "fragment": "one runtime file containing one unreleased ChangeEvent",
}


def get_glossary() -> dict[str, str]:
    return dict(GLOSSARY)
