# Docker test isolation and dependency policy

Docker recipes are clean-room consumers of the repository. They must not inherit
the operator's harness configuration, generated provider surfaces, credentials,
caches, runtime records, or development-only skills.

## Image layers

1. `Dockerfile.test-base` supplies operating-system infrastructure only: Python,
   Node/npm, Git, CA/curl, native compilation support, `procps`, and `uv`.
2. A recipe may add expensive platform prerequisites, such as Rust or Go, when
   those compilers are not the behavior under test. Keep them in that recipe or
   a purpose-built derived cache image.
3. Provider CLIs, editors, language servers, and harness configuration are not
   base-image inputs. Lifecycle tests invoke AUDiaGentic to install, configure,
   probe, exercise, and uninstall them.

This distinction keeps performance caching without turning the base into a
developer-machine snapshot that makes missing lifecycle behavior invisible.

## Context and home isolation

- `COPY . /app` and `ADD . /app` are prohibited. Every recipe lists its inputs.
- Copying `.claude`, `.codex`, `.config`, or `.cache` is prohibited.
- Mutating recipes set both `HOME` and `AUDIAGENTIC_HOME` below `/tmp`.
- Project-owned generated surfaces are copied only by a test explicitly checking
  an existing projection. A fresh-install or lifecycle recipe starts without them.
- Docker socket mounts, host-home mounts, credential forwarding, and bind-mounted
  source are not part of canonical clean-room gates.

`tests/unit/docker/test_docker_recipe_isolation.py` enforces the static parts of
this contract.

## Dependency strength

Prefer, in order:

1. A version declared by the provider/component descriptor and installed by AG.
2. A pinned recipe prerequisite with a checksum or immutable image digest.
3. A versioned package-repository install when checksum distribution is external.

Avoid `latest`, unversioned Git branches, and remote `curl | sh` installers for
product dependencies. Current Rust and `uv` bootstrap scripts remain build-time
infrastructure risks; they should move to checksum-verified artifacts when the
repository establishes a shared dependency lock. Their presence must never be
used instead of exercising AG lifecycle installation.

## Viability check for a new harness recipe

From a newly built minimal base, prove in order:

1. The harness executable is absent before the test.
2. AG lifecycle installation succeeds and the provider probe reports its version.
3. AG materializes native default configuration into the disposable home.
4. A direct native launch sees the expected functional MCP surface.
5. An isolated job launch sees only its requested MCP surface.
6. Concurrent jobs do not share artifacts or configuration.
7. AG uninstall removes owned binaries/config while preserving foreign sentinel
   files created by the test.
8. A second install/uninstall cycle succeeds from the same clean image.

If the harness is not installable by AG (for example, a host GUI application),
the recipe must call that out as an explicit platform prerequisite and test only
the lifecycle/configuration capabilities AG actually owns.
