# PyPI publishing

The release workflow builds a wheel and source archive for every release and
uploads both to the GitHub Release. It also publishes to PyPI using GitHub
Trusted Publishing (OIDC), without a long-lived PyPI API token.

## One-time PyPI setup

Create the `audiagentic` project on PyPI, or open its publishing settings if it
already exists. Add a GitHub Trusted Publisher with:

```text
 owner: Audumla
 repository: AUDiaGentic
 workflow: .github/workflows/release.yml
 environment: (leave empty)
```

PyPI may label this a pending publisher until the first matching workflow run.
No GitHub secret or `PYPI_PUBLISH` variable is required.

## Publishing

Merge a release-producing change to `main` (or run the supported release
workflow on a `proof-release-*` branch). Release-please creates the tag; the
release job then builds, uploads the GitHub assets, and publishes to PyPI.

## Installing and updating

On a new machine with Python 3.10 or newer:

```bash
python3 -m venv ~/.venvs/audiagentic
source ~/.venvs/audiagentic/bin/activate
python -m pip install --upgrade audiagentic
```

Existing installations update with the same command:

```bash
python -m pip install --upgrade audiagentic
```

GitHub Release assets remain available even when PyPI publishing is disabled.
