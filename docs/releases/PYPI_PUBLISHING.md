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
No GitHub secret is required. Publishing to PyPI only happens when the repository
variable `PYPI_PUBLISH` is `true`; the GitHub Release assets are always attached.

OIDC removes the need for a stored PyPI publishing token; it does not sanitize
source files or distribution contents. GitHub assets, PyPI packages, release
notes and CI evidence are public outputs. Follow the
[public repository boundary and incident guidance](../standards/SECRETS_MANAGEMENT.md#public-repository-boundary)
before publishing. Local paths and diagnostic identifiers can disclose private
information even when no API credential is present.

## Publishing

Merge a release-producing change to `main` (or run the supported release
workflow on a `proof-release-*` branch). The repository release workflow finds
the bot-generated release PR, validates its exact head with the fast CI gate,
and merges that same head through the normal pull-request rules. It then
explicitly dispatches the next release run: merges made with `GITHUB_TOKEN`
do not trigger push workflows themselves. No manual release-PR merge is needed.

Release-please creates the tag after that merge. Ledger finalization, tests
against the finalized source, distribution validation, GitHub asset upload,
and PyPI publication follow automatically. A failed validation or changed PR
head blocks automatic merging; repository protections are not bypassed.

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
