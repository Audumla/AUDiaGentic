# Release Notes

## v0.4.2

### Configuration
- Clean up generated root artifacts without disrupting local agent setup; prevent their return to Git and Docker builds.

### Workflow
- Release version bumps now validate and merge automatically, then continue to build and PyPI publication without a manual release-PR merge.
