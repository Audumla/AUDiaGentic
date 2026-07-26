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
| Development (interactive) | Shell `export OPENROUTER_API_KEY=...` — key never touches disk |
| Development (tests) | `.audiagentic/secrets/test.env` (auto-loaded by `tests/conftest.py`) |
| Development (production-like) | `.audiagentic/secrets/prod.env` (set `AUDIAGENTIC_ENV=prod`) |
| CI | Provider secret management (GitHub Actions secrets, etc.) |
| Docker | `tests/docker/provider-lifecycle.env` (copy from `.env.example`) |
| GitHub OAuth | `~/.audiagentic/credentials/github_token.json` (`0o600`); env vars take priority |
| Gateway token | `<service_root>/auth.token` (`0o600`) |

`.env.example` at project root is the tracked template. `.env` and `.audiagentic/` are gitignored.

### Environment-specific secrets files

The `AUDIAGENTIC_ENV` variable selects which secrets file to load:

- `test` (default): loads `.audiagentic/secrets/test.env`
- `prod`: loads `.audiagentic/secrets/prod.env`

`tests/conftest.py` loads the file via `python-dotenv` at startup. The file is never committed —
it lives in `.audiagentic/` which is gitignored.

```bash
# For testing with real keys:
echo 'OPENROUTER_API_KEY=sk-or-v1-...' > .audiagentic/secrets/test.env
pytest tests/unit/providers/

# For production-like testing:
export AUDIAGENTIC_ENV=prod
echo 'OPENROUTER_API_KEY=sk-or-v1-...' > .audiagentic/secrets/prod.env
pytest tests/integration/
```

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
