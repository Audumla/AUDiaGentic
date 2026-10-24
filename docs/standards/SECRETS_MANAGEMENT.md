# Secrets Management

## Core Rule

Secrets use **resolve-at-boundary** pattern. The reference `env:VAR_NAME` is an
opaque string through config; resolution happens once at the call site that needs
the value. Never cache, persist, log, or surface the resolved value.

## Reference Format

```
env:<UPPER_SNAKE_CASE_VAR_NAME>
```

- Scheme: `env` (only built-in; extensible via `register_secret_scheme()`)
- Invalid refs raise `VAL-CRED-001`. Missing env vars raise `CON-CRED-001`.

```python
from audiagentic.components.providers.services.secrets import (
    parse_secret_ref,      # "env:NAME" → SecretRef
    resolve_secret_ref,    # SecretRef → actual value
    has_ambient_value,     # check presence without resolving
)
# SecretRef.__str__ never includes the resolved value
```

## Environment Variables

### Vendor Keys

| Env Var | Vendor | Providers |
| --- | --- | --- |
| `OPENAI_API_KEY` | OpenAI | pi, qwen, codex, opencode |
| `ANTHROPIC_API_KEY` | Anthropic | pi, qwen, claude |
| `GEMINI_API_KEY` | Google | pi, qwen, gemini |
| `OPENROUTER_API_KEY` | OpenRouter | pi |
| `DASHSCOPE_API_KEY` | DashScope | qwen |

### Internal Keys

| Env Var | Purpose |
| --- | --- |
| `AUDIAGENTIC_GITHUB_TOKEN` | GitHub OAuth (highest priority) |
| `GITHUB_TOKEN` / `GH_TOKEN` | GitHub fallbacks |
| `AUDIAGENTIC_ENV` | Secrets file selector (`test`/`prod`) |

Vendor keys use the vendor's convention. Internal keys are `AUDIAGENTIC_`-prefixed.

## Storage

| Context | How |
| --- | --- |
| Development (interactive) | Process environment from an approved secret store; avoid literal values in shell history |
| Development (tests) | `.audiagentic/secrets/test.env` (auto-loaded by `tests/conftest.py`) |
| Development (production-like) | `.audiagentic/secrets/prod.env` (set `AUDIAGENTIC_ENV=prod`) |
| CI | Provider secret management (GitHub Actions secrets, etc.) |
| Docker | `tests/docker/provider-lifecycle.env` (copy from `tests/docker/provider-lifecycle.env.example`) |
| GitHub OAuth | `~/.audiagentic/credentials/github_token.json` (`0o600`); env vars take priority |
| Gateway token | `<service_root>/auth.token` (`0o600`) |

`.env.example` at project root is the tracked template. `.env` and `.audiagentic/` are gitignored.

### Environment-specific secrets files

The `AUDIAGENTIC_ENV` variable selects which secrets file to load:

- `test` (default): loads `.audiagentic/secrets/test.env`
- `prod`: loads `.audiagentic/secrets/prod.env`

`tests/conftest.py` loads the file via `python-dotenv` at startup. The file is never committed —
it lives in `.audiagentic/` which is gitignored.

Populate the ignored file through an approved secret manager or secure local
editor; do not put literal credentials in shell commands, history, or examples.
Restrict file access using the operating system's permissions. Then select the
environment without repeating its secret values:

```bash
pytest tests/unit/providers/
AUDIAGENTIC_ENV=prod pytest tests/integration/
```

## Public repository boundary

### Public metadata placeholders and enforcement

Use role-based placeholders rather than machine-specific values in public docs:

| Private value | Public representation |
| --- | --- |
| Developer checkout | `{dev-root}/audiagentic/...` |
| User home | `{user-home}/...` |
| Developer or build endpoint | `{dev-host}` or `{build-host}` |
| Provider conversation/project link | `{gpt-chat-url}` or `{gpt-project-url}` |
| Recorded request/session identity | An explicit `req_example_...` / `ses_example_...` fixture, or descriptive placeholder |

Keep real endpoint values in ignored local configuration or environment
variables. Public executable defaults use loopback, not a documentation
placeholder or a private network address. Do not replace a running service's
local configuration with example values.

Synthetic fixtures must be clearly distinguishable from captured identities.
The privacy policy reserves project IDs with a sixteen-zero prefix and UUIDs
with the `00000000-0000-4000-8000-` prefix for generated examples; ordinary
request/session fixtures use an explicit `example` component. Existing technical
fixtures may retain URL structure, but never a real provider identity. No test
directory is exempt from scanning.

The shared scanner runs against the Git index, not unstaged working files:

```bash
python tools/privacy_guard.py --all
python tools/privacy_guard.py --staged
python tools/privacy_guard.py --install-hook
```

Hook installation refuses to overwrite an existing hook configuration. Integrate
the staged command into an existing hook deliberately. Local hooks can be
bypassed, so the server-side required `privacy` check is the enforcement boundary.
It checks the complete proposed tree and every introduced commit, including
commit messages, so adding a private value and deleting it in a later commit
does not evade rejection.

The GitHub workflow reads its scanner and binary registry from the trusted base,
never executes PR source code, and publishes the result for the exact PR head.
Release and ledger automation must run this gate before posting the same required
status. Reports contain sanitized paths, line numbers and categories, not values.

Additional private machine terms belong only in the ignored
`.audiagentic/privacy/terms.txt` or the `AUDIAGENTIC_PRIVATE_TERMS` environment
variable/repository secret. Do not commit the literal denylist. Fork PRs are
scanned as data by the trusted workflow; they cannot replace the policy with
their own scanner or read the repository term list through executable PR code.

Opaque files fail closed unless their exact path and digest are in
`tools/privacy_binary_allow.json`. This registry covers reviewed canonical icons,
not screenshots or arbitrary diagnostics; updating it requires deliberate review.
The mechanical redaction tool is dry-run by default:

```bash
python tools/redact_private_metadata.py
python tools/redact_private_metadata.py --write
```

Review and test the result before staging. Metadata normalization is not a
credential scanner and does not replace rotation or GitHub secret scanning.

Treat every tracked file, commit message, PR description, release note, package
archive and uploaded CI artifact as potentially public. A public repository
does not make local project data safe to publish.

- Track source, canonical templates and empty/example configuration only.
- Keep resolved credentials, cookies, browser profiles, local provider settings,
  runtime journals, raw DOM captures and screenshots out of Git. Sanitize any
  deliberately shared diagnostic fixture before staging it.
- Remove machine-specific paths, personal identifiers, internal addresses,
  provider chat URLs and request/session IDs from new public diagnostic docs
  unless their publication is intentional and necessary. These are not always
  credentials, but can still disclose private operational information.
- Keep generated root harness instructions and local provider configuration
  untracked. Canonical nested templates remain source-controlled.
- Never paste matching secret values into a bug report or scanner report.
  Report the path, line, credential category and remediation status instead.

`.gitignore` prevents adding matching untracked files; it does not untrack an
already tracked file, inspect file contents, or remove historical copies.
Before committing, inspect these metadata-only summaries, then review the
actual diff locally without sharing credentials:

```bash
git status --short
git diff --cached --name-status
git diff --cached --check
git ls-files -ci --exclude-standard
git check-ignore --no-index .env .audiagentic/secrets/test.env .agents/mcp_config.json
```

An ignored-but-tracked result requires review, not indiscriminate removal:
historical source archives and intentionally retained fixtures may also match
ignore rules. Use explicit paths when untracking; preserve needed local copies.

### Audit snapshot and limitations (2026-10-24)

A fresh remote bare clone was scanned across all reachable branch/tag text
blobs (60,197 blobs, approximately 612 MB of historical text). The targeted
patterns covered GitHub tokens, common vendor API keys, AWS access IDs, Slack
tokens, JWTs and private-key headers. Matches were confined to AWS-shaped test
strings and private-key header examples; no encoded private-key body was found.
This is a limited pattern audit, not proof that credentials or private data
are absent, and no credential validity checks were performed.

Existing planning/release records still contain machine-specific paths,
internal endpoint references and provider request/chat identifiers. Those
require a separate privacy-redaction review; the generated-file history purge
did not remove every occurrence of operational metadata from document content.

At this audit, GitHub secret scanning and secret-scanning push protection were
both **disabled**. Therefore no assurance can be drawn from the absence of
GitHub alerts. Enable them through an explicitly authorized repository-settings
change and verify their state; documentation and ignore rules are not a scanner.

The local audit report stores only object IDs, paths, line numbers and match
categories, not matching credential values. Raw evidence remains outside the
repository. Re-run a maintained credential scanner before treating this
snapshot as a security sign-off; arbitrary passwords and private narrative
content need additional review.

### If a real credential was published

1. Revoke or rotate the credential first; deleting a file is not revocation.
2. Stop further disclosure, review usage/access logs, and record sanitized
   incident metadata. Do not copy the secret into a remediation commit.
3. Remove or replace the value in the current tree and review packages, CI
   artifacts, logs, releases and other exported copies separately.
4. If history removal is needed, coordinate exact paths/content replacements,
   backups, collaborators and protected refs before rewriting. Restore any
   temporarily changed repository protection immediately afterward.
5. Use a fresh clone or transfer only reviewed changes onto cleaned history.
   Do not merge old history back. Backups, forks and GitHub PR/cache references
   can retain old objects even after writable branches/tags are rewritten.

See GitHub's [secret-removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
and [secret-scanning guidance](https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning).

## Redaction

Applied at every output boundary via `foundation/logging/redaction.py`.

**Pattern-based** (`DEFAULT_REDACT_PATTERNS`): bearer tokens, `sk-*`/`ghp-*`/etc. tokens,
base64 secrets, `key=value` pairs, URL-embedded credentials.

**Structural** (`SECRET_KEYS`): dict keys matching `key|token|secret|password|auth`
→ value replaced with `[REDACTED]`.

**Boundaries**: MCP errors, subprocess stdout, streaming output, event observers,
gateway records, operational records, managed block writes, error envelopes.

**Admission scanning**: `sk-*`, `AKIA*`, `Bearer *`, `-----BEGIN PRIVATE KEY-----`
rejected before gateway. Worker protocol rejects top-level `env`, `secret`, `token`,
`credential` keys.

## Test Patterns

### Unit tests: `monkeypatch.setenv()`

```python
def test_secret_resolves(monkeypatch) -> None:
    monkeypatch.setenv("TEST_SECRET_VALUE", "canary-secret")
    ref = parse_secret_ref("env:TEST_SECRET_VALUE")
    assert resolve_secret_ref(ref) == "canary-secret"
```

### Shared fixture: `fake_secret_ref`

Sets a fake env var and returns the `env:NAME` ref string:

```python
def test_provider_needs_api_key(fake_secret_ref) -> None:
    ref = fake_secret_ref("OPENAI_API_KEY")
    assert has_ambient_value(ref) is True

def test_custom_value(fake_secret_ref) -> None:
    ref = fake_secret_ref("MY_KEY", fake_value="custom-secret-123")
    assert resolve_secret_ref(ref) == "custom-secret-123"
```

### Integration tests: skip when absent

```python
required_env = ("OPENAI_API_KEY",)
if not all(os.environ.get(k) for k in required_env):
    pytest.skip("real API key not set")
```

### Docker tests

```bash
cp tests/docker/provider-lifecycle.env.example tests/docker/provider-lifecycle.env
AUDIAGENTIC_DOCKER_TESTS=1 pytest tests/integration/
```

### Smoke tests: dummy fallback

```bash
export OPENAI_API_KEY="${OPENAI_API_KEY:-dummy}"
```

## Adding a New Secret

1. Pick env var name: `UPPER_SNAKE_CASE`, vendor-prefixed or `AUDIAGENTIC_`-prefixed
2. Declare in provider YAML (vendor key):

   ```yaml
   vendor_key_injection:
     myvendor: {mechanism: env, key: MYVENDOR_API_KEY}
   ```

3. Or reference in config (provider auth):

   ```yaml
   access_mode: "env"
   auth-ref: "env:MYVENDOR_API_KEY"
   ```

4. Add to `.env.example` (commented out)
5. Add skip guard for integration tests
6. **Never** put actual keys in YAML, source, test fixtures, or docs

## Anti-Patterns

| Don't | Why |
| --- | --- |
| Put literal API keys in YAML | Committed to git |
| Log `resolve_secret_ref()` output | Redaction may miss it |
| Cache secrets in module globals | Persists beyond call frame |
| Return `SecretRef` with resolved value | `__str__` hides values by design |
| Put secrets in test fixture files | Fixtures are often committed; use `monkeypatch` |
| Use `print()` for secret-adjacent output | Use `logger` with `extra` fields |
| Commit `.env` files | Always gitignored, verify before push |
| Use `api-key` as YAML key name | Matches `SECRET_KEYS` denylist; use `auth-ref` |
| Hardcode keys in test scripts (`os.environ[...]`) | Key written to disk on every edit; set env var externally or via `.audiagentic/secrets/test.env` |
