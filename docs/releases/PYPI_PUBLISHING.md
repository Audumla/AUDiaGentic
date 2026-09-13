# PyPI publishing

The release workflow builds a wheel and source archive for every release and
uploads both to the GitHub Release. It publishes to PyPI only when explicitly
enabled.

## One-time repository setup

Create a PyPI API token scoped to the `audiagentic` project, then configure it
in GitHub. Using GitHub CLI:

```bash
gh variable set PYPI_PUBLISH --repo Audumla/AUDiaGentic --body true
gh secret set PYPI_API_TOKEN --repo Audumla/AUDiaGentic
```

The second command prompts for the token and does not store it in the
repository. Do not commit the token or place it in project `.env` files.

## Publishing

Merge a release-producing change to `main` (or run the supported release
workflow on a `proof-release-*` branch). Release-please creates the tag; the
release job then builds and publishes the artifacts.

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
