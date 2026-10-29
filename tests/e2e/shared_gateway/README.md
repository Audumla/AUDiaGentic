# Installed shared-gateway native qualification

This opt-in SH37/SH42 test runs real Codex CLI work (potentially paid). It tests
server-hosted execution, not joining a human session or caller-local node execution.
It does not install integrations, alter the source tree, or modify the source catalog.

Use a Python environment with PyYAML and cryptography. Supply either an installed
`pip --target` directory including dependencies or an explicit wheel (the runner
installs that wheel and its dependencies into its new evidence directory).
The existing native profile must be present in the supplied machine catalog,
select provider `codex` and have `surface_id=None` (no surface override).
ACP and all other surface overrides are rejected, including a `codex-cli` override:
CLI is an access mode, not a declared session surface. The runner deep-copies the
profile under a fresh UUID-suffixed qualification ID, retains surface None, and
passes that ID to child clients through generated client configuration. The source
entry is never overwritten, even when it is named `qualification-codex-cli`.
Provider configuration explicitly selects CLI and submissions disable session keep-alive.
Codex must already be authenticated and available on PATH. Its normal native
credential/configuration reads remain necessary; the AUDiaGentic catalog is isolated.

Run outside the source checkout, with absolute input paths:

```text
python -I /path/to/tests/e2e/shared_gateway/qualify_native.py --installed-package /path/to/installed --catalog /path/to/config/agents.yaml --native-profile EXISTING_PROFILE --provider codex --access-mode cli --output /path/to/new-evidence-directory
```

Replace `--installed-package DIR` with `--wheel /path/to/package.whl` if desired.
Output must not already exist. It namespaces both workspaces under that directory,
copies the catalog into `machine/config/agents.yaml`, and sets AUDIAGENTIC_HOME
before importing the installed application. Subprocess PYTHONPATH points only at
the supplied installation. No checkout fallback is accepted by the driver.

The pytest entry point uses the registered `opt_in` marker and additionally requires
`AUDIAGENTIC_RUN_SHARED_NATIVE_E2E=1`. Set `AUDIAGENTIC_SHARED_NATIVE_ARGS` to a JSON
array containing the same explicit command arguments, then run:

```text
python -m pytest tests/e2e/shared_gateway/test_native_qualification.py -m opt_in
```

The proof sequence creates ephemeral TLS and separate principal tokens; checks
proxy exclusion and invalid project/root envelopes with a valid lease; starts an
installed service; drops the first successful admission response; retries the same
key from another submitter process; asserts the same admitted request and one
persisted native attempt; and observes both workspace-specific file markers from
separate processes. Observers receive only IDs/credentials and never read server
workspace files. After all submitter/observer processes exit and reader leases close,
the service must remain alive. A reader acquires a fresh lease before server restart,
then must reattach using its cached stale lease. Fresh child readers must retrieve
the same terminal outputs after restart. Cached-reader failures fail qualification.

`proof.json`, installed-server logs and observer logs retain the assertions and
native attempt evidence. One persisted attempt is the available gateway accounting
proof, not an independent packet trace of the native provider. The proof is local
TLS/multiprocess evidence, not two-machine or mixed-OS qualification. Run on each
claimed platform separately. Exceptions/timeouts register subprocess cleanup through
ExitStack; Windows uses kill-on-close jobs assigned before children resume (taskkill /T is
a setup-failure fallback); POSIX uses isolated process groups. Cleanup
never selects unrelated processes by executable name. As with any process cleanup,
forced OS termination cannot execute Python finally handlers; Windows job handles
still close with the driver, whereas POSIX cleanup requires the driver to run.

Evidence contains ephemeral private keys, bearer tokens, the copied catalog, and
native output. Keep the directory private (on Windows use a user-only ACL), never
commit it, and remove it after retaining a redacted proof. chmod is not a Windows ACL.
No secrets or evidence are written into tracked qualification files.

Non-native validation:

```text
python -m pytest tests/e2e/shared_gateway/test_qualification_smoke.py
python -m pytest tests/e2e/shared_gateway/test_native_qualification.py --collect-only
```
