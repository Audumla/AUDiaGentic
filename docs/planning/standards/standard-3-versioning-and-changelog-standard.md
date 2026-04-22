---
id: standard-3
label: Versioning and changelog standard
state: ready
summary: Default standard for version numbering and changelog maintenance across installable
  planning-enabled projects.
---







# Standard

Default standard for version numbering and changelog maintenance in AUDiaGentic-based projects.

# Source Basis

This standard is derived from Semantic Versioning 2.0.0 and Keep a Changelog, adapted for the repository's template and documentation-sync model.

Sources:

- [Semantic Versioning 2.0.0](https://semver.org/)
- [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)

# Requirements

1. Public-facing version identifiers should follow Semantic Versioning unless a project explicitly documents a different version contract.
2. Changelogs must be maintained in a human-readable form. They are not commit dumps.
3. Changelog structure should follow Keep a Changelog categories where practical:

   - Added
   - Changed
   - Deprecated
   - Removed
   - Fixed
   - Security

4. Projects should maintain an `Unreleased` section while changes are in progress, then roll those entries into a released version entry at release time.
5. Changelog entries should describe user-visible or operator-visible impact rather than internal implementation noise.
6. Documentation-sync rules may require `CHANGELOG.md` updates, but automated tools must not auto-edit project docs without explicit instruction.
7. Template-installed projects may own their own changelog content, so changelog handling must respect the configured ownership mode.
8. Breaking changes must be flagged explicitly in changelog entries and in version increments (major bump for public APIs).

# Default Rules

- If a change affects a project-facing documentation surface or installable planning behavior, evaluate whether `CHANGELOG.md` should be updated.
- Prefer short, specific release notes over vague summaries.
- Keep versioning and changelog decisions visible in planning and release documentation.
- Do not include internal planning record IDs in user-facing changelogs unless they add traceability value for operators.

# Non-Goals

- Defining Git workflow or branching policy.
- Replacing project-specific release governance.
- Forcing automatic release-note generation.
