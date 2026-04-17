## Summary
The AUDiaGentic release system automates version management, release preparation, and changelog generation. It integrates with release-please for semantic versioning, manages release fragments, imports commit history, and handles release finalization workflows.

## Current state
**Release System** (`src/audiagentic/release/`):

**Release Management:**
- **Bootstrap** (`bootstrap.py`): Initialize release system configuration
- **Finalize** (`finalize.py`): Complete release preparation and publishing
- **Audit** (`audit.py`): Audit release artifacts and processes
- **Sync** (`sync.py`): Synchronize release state with repositories

**Changelog Generation:**
- **Fragments** (`fragments.py`): Manage release fragments (keep-changelog style)
- **History Import** (`history_import.py`): Import git commit history into fragments
- **Current Summary** (`current_summary.py`): Generate summary of current release changes
- **Release Please** (`release_please.py`): Integrate with release-please for semantic versioning

**Core Capabilities:**
- Semantic versioning: automatic version bumps based on commit types
- Fragment management: keep-a-changelog style release notes
- History import: convert git commits to release fragments
- Release finalization: prepare and publish releases
- Release auditing: verify release integrity
- State synchronization: keep release state in sync

**Integration Points:**
- Execution system: jobs trigger release operations
- Planning system: release tasks tracked as artifacts
- Git repository: commits drive version bumps
- Package registries: publish releases to npm, PyPI, etc.

## How to use
**Release Bootstrap:**

```python
from audiagentic.release import bootstrap

## Initialize release system
bootstrap.initialize(
    target_path=".",
    version="1.0.0",
    package_name="audiagentic"
)
```

**Fragment Management:**

```python
from audiagentic.release import fragments, history_import

## Add release fragment
fragments.add_fragment(
    category="added",
    description="New feature implementation",
    reference="task-0001"
)

## Import git history
history_import.import_commits(
    since_tag="v1.0.0",
    output_dir="docs/release-fragments/"
)

## Generate current summary
summary = current_summary.generate(
    fragments_dir="docs/release-fragments/",
    include_categories=["added", "changed", "fixed"]
)
```

**Release Finalization:**

```python
from audiagentic.release import finalize, release_please

## Prepare release
finalize.prepare_release(
    version="1.1.0",
    changelog="docs/CHANGELOG.md",
    fragments_dir="docs/release-fragments/"
)

## Use release-please
release_info = release_please.prepare_release(
    repo="audiagentic/AUDiaGentic",
    target_branch="main"
)

## Finalize and publish
finalize.publish_release(
    version="1.1.0",
    tag="v1.1.0",
    artifacts=["dist/*"]
)
```

**Release Audit:**

```python
from audiagentic.release import audit

## Audit release
audit_result = audit.release(
    version="1.1.0",
    checklists=["artifacts", "changelog", "tags"]
)

## Audit specific component
artifact_audit = audit.artifacts(
    version="1.1.0",
    expected=["package.tar.gz", "wheel.whl"]
)
```

**CLI Operations:**

```bash
## Bootstrap release system
python -m src.audiagentic.channels.cli.main release-bootstrap --target .

## Import commit history
python -m src.audiagentic.release.history_import --since-tag v1.0.0

## Generate release summary
python -m src.audiagentic.release.current_summary --fragments-dir docs/release-fragments/

## Finalize release
python -m src.audiagentic.release.finalize --version 1.1.0
```

**Workflow:**
1. Bootstrap release system on project initialization
2. Add fragments for each significant change
3. Import git history periodically
4. Generate summary before release
5. Use release-please for version calculation
6. Finalize release with changelog
7. Publish to package registries
8. Audit release artifacts

## Sync notes
This page should be refreshed when:
- New release operations are added
- Fragment schema changes
- Release-please integration is modified
- New package registries are supported

**Sources:**
- `src/audiagentic/release/` - Release implementation
- Release configuration in `.audiagentic/release/`
- Release fragments in `docs/release-fragments/`

**Sync frequency:** On release system changes

## References
- [Execution System](./system-execution.md)
- [Planning System](./system-planning.md)
- [Release Please](https://github.com/googleapis/release-please)
- [Keep a Changelog](https://keepachangelog.com/)
