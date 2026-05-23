# Changelog

## [0.2.0](https://github.com/Audumla/AUDiaGentic/compare/v0.1.1...v0.2.0) (2026-05-23)


### Features

* add audiagentic refresh CLI and refresh_harness_config MCP tool ([a6eef70](https://github.com/Audumla/AUDiaGentic/commit/a6eef7045121fbb2f0294bd5e6cf98228e269e75))
* add description/url metadata to all provider descriptors; reconcile on launch ([0dac967](https://github.com/Audumla/AUDiaGentic/commit/0dac9677bdf483f637bb06a39412ee7e66d08278))
* add provider model catalog fetching ([22f4979](https://github.com/Audumla/AUDiaGentic/commit/22f4979902583ec4a4e323d95863ec46c1c88935))
* add startup status output to audiagentic launcher ([8c8a8db](https://github.com/Audumla/AUDiaGentic/commit/8c8a8dbcf3448284b7befc59bd66834022fa91f7))
* audiagentic component CLI + release wheel test ([5d0a316](https://github.com/Audumla/AUDiaGentic/commit/5d0a316d945eda33ca179c1eef1a806f3bf1b290))
* default model to qwen3.5-2b-q4_k_s ([625953c](https://github.com/Audumla/AUDiaGentic/commit/625953cf6c87a253fef576e921166bca742c4fdb))
* enable MCP, disable builtin tools, block all slash commands ([ddfbd36](https://github.com/Audumla/AUDiaGentic/commit/ddfbd36ea43e001789483322d3ad4dea6f91b569))
* fetch model catalog on provider first enable ([1a0b2b7](https://github.com/Audumla/AUDiaGentic/commit/1a0b2b78751cd3717de9f0ea0a91215eca4a4f7c))
* harness-scoped components + auto-update subsystem ([402ca3d](https://github.com/Audumla/AUDiaGentic/commit/402ca3d5150bed43b554616bcb3d2f7fc5b365f5))
* hide audiagentic_ MCP tool call blocks in Pi TUI ([840a17b](https://github.com/Audumla/AUDiaGentic/commit/840a17b685bec647d68bf8f450c554b1113919e7))
* hide thinking block in agent UI ([8d3f917](https://github.com/Audumla/AUDiaGentic/commit/8d3f917a24ba0afebb82fd57c4927ec92838576a))
* include VS Code extension status in list_providers and provider_status ([45cb22f](https://github.com/Audumla/AUDiaGentic/commit/45cb22f47a6743c7984a40f052a5d18ac99ecb93))
* ledger-git linkage, release flow fixes, probe field, config-driven MCP names ([09f07f4](https://github.com/Audumla/AUDiaGentic/commit/09f07f465b23d8881a39cbcbbfe50026774b857a))
* **project-server:** surface source-control availability and warnings on install ([ec3ff44](https://github.com/Audumla/AUDiaGentic/commit/ec3ff4450beeb4fa9f42e30585b0d02d253ade64))
* provider lifecycle — install/uninstall, enable/disable, surface maintenance ([c8de3f8](https://github.com/Audumla/AUDiaGentic/commit/c8de3f88131bf34ab80c7d049d711e83e75594bb))
* reconcile_provider — auto-sync providers.yaml with host CLI state ([b27010c](https://github.com/Audumla/AUDiaGentic/commit/b27010cae83d8a4b58ab353778ca92aeb60a046f))
* **source-control:** two-step dependency installer for git/gh/gh-mcp/uv ([ce5626f](https://github.com/Audumla/AUDiaGentic/commit/ce5626f1c4cdb046fa2ec7d77d9acde855837bf9))
* suppress providers MCP tool call display in Pi TUI ([792d30d](https://github.com/Audumla/AUDiaGentic/commit/792d30d14cd02819d537d9e0190d90c11bb0635f))
* surface install_method from descriptor; add vscode toolchain for roo ([9148cb5](https://github.com/Audumla/AUDiaGentic/commit/9148cb575a559d47c6826cadea694363cc16a75e))
* tighten agent scope boundary, decline all off-topic requests ([c503224](https://github.com/Audumla/AUDiaGentic/commit/c503224bbbeaa204ad7148dd90f9fc83f94b8bba))


### Bug Fixes

* add release proof marker ([6e7adbe](https://github.com/Audumla/AUDiaGentic/commit/6e7adbefb833b3be88054d72800942cd4eb199bc))
* correct copilot install recipe from npm to gh-extension ([c7b4208](https://github.com/Audumla/AUDiaGentic/commit/c7b4208c97778c44b8bbb3465f26aa8bfd2c96c7))
* correct release component detection path in project_server ([af59efa](https://github.com/Audumla/AUDiaGentic/commit/af59efaf149f1b60e733e6329cdade2e7362202e))
* correct VS Code extension IDs and rewrite detection to use filesystem ([83891d8](https://github.com/Audumla/AUDiaGentic/commit/83891d8c57d48ed5662f19f0523901ff7730d8e6))
* graceful self-update on Windows frozen exe via detached installer ([c789aab](https://github.com/Audumla/AUDiaGentic/commit/c789aab1158c5be4d9c49669e70ce7ace5e76006))
* pass --alias &lt;profile-name&gt; to llama-server so /v1/models returns configured ID ([63bb36d](https://github.com/Audumla/AUDiaGentic/commit/63bb36d8a861a8dab18df8bc347f576df97c9b6f))
* patch MCP OAuth callback server to bind 127.0.0.1 instead of localhost ([e033165](https://github.com/Audumla/AUDiaGentic/commit/e033165ed409aa3df6e603ac891857f56c6c83d3))
* pi_args reference missed in rename, use agent_args ([7acdcd6](https://github.com/Audumla/AUDiaGentic/commit/7acdcd69d6f7c1f463cc81c6ec887ac00026b5ee))
* prevent VS Code launch during reconcile ([c027ef8](https://github.com/Audumla/AUDiaGentic/commit/c027ef86fa139390f38551331ae31bf1d68e62ed))
* **project-server:** regenerate mcp.json after component state changes via MCP tools ([bcc4b24](https://github.com/Audumla/AUDiaGentic/commit/bcc4b24abd1805a41929b140deccafda4ab4e032))
* provider cleanup ([5af0039](https://github.com/Audumla/AUDiaGentic/commit/5af003942c3d1c83232131a8a53b84659dd5610e))
* provider update ([e4c53b7](https://github.com/Audumla/AUDiaGentic/commit/e4c53b747481b0c4b7e65571343c09c64f145cb1))
* read AGENT_VERSION from package instead of hardcoded PI version ([fd6a754](https://github.com/Audumla/AUDiaGentic/commit/fd6a75451d4f8986ffe183691d2406510efe0402))
* reap orphan llama-server processes before starting a fresh rig ([03c7ed0](https://github.com/Audumla/AUDiaGentic/commit/03c7ed004065453586e4c763864655a59b6601f9))
* release-test wheel install, MCP project-root isolation, release-bootstrap CLI ([0d62b48](https://github.com/Audumla/AUDiaGentic/commit/0d62b4881fb0ba3f15e425625a5e0e3df7d5ce0b))
* **release:** lock pre-1.0 version policy ([171117c](https://github.com/Audumla/AUDiaGentic/commit/171117cd2871f35e3bcd41e7bc677bc6b9747887))
* remove extra templates/ nesting, path was templates/templates/home ([2fea2ce](https://github.com/Audumla/AUDiaGentic/commit/2fea2ced35982cc06b44f2bb898a12ef5724f5f9))
* replace null with empty defaults in providers MCP tool responses ([e8edbf2](https://github.com/Audumla/AUDiaGentic/commit/e8edbf2fd7e88455221a012f310e91acb246b737))
* resolve Docker collection error in component lifecycle tests ([e9dc7e3](https://github.com/Audumla/AUDiaGentic/commit/e9dc7e3d3756c4007da80cd952779bbf64200407))
* roo probe checks extension install; reconcile corrects stale enabled state ([f2cf8c7](https://github.com/Audumla/AUDiaGentic/commit/f2cf8c73121caa52043288609220a60304d767dc))
* seed install-mode/access-mode when reconcile enables a new provider ([e46cb3d](https://github.com/Audumla/AUDiaGentic/commit/e46cb3d528c263258f80ecd33b90af5cd2f97a20))
* **source-control:** post-commit hook shebang placement caused Exec format error ([e09f16f](https://github.com/Audumla/AUDiaGentic/commit/e09f16f5707e9e2f3bc556614eee1f53d47b59c5))
* suppress Pi self-version-check notification, update scaffold test paths ([9257318](https://github.com/Audumla/AUDiaGentic/commit/9257318d08cfc87e27104144c97622c6696fb8c3))
* surface components use actual surface files as detection markers ([fa8ed68](https://github.com/Audumla/AUDiaGentic/commit/fa8ed682af29e31feb65f95a617762d13c719877))
* three update/OAuth bugs found in live testing ([0e1219a](https://github.com/Audumla/AUDiaGentic/commit/0e1219ac2845f1d91a5040022669be3b8971aac2))
* tighten dependency and provider validation ([0d3507d](https://github.com/Audumla/AUDiaGentic/commit/0d3507d58f7e3b9e027d6d9ad4c82197be0b329f))
* update copilot to npm install; add per-provider command tests ([0c5d8ab](https://github.com/Audumla/AUDiaGentic/commit/0c5d8abb409387b181d87205e09b032713fb2004))
* updated llamacpp ([27fa33b](https://github.com/Audumla/AUDiaGentic/commit/27fa33b137c7302e1c72f12fea959504cc073f64))


### Documentation

* relax scope boundary - help/ambiguous requests explain capabilities ([8906210](https://github.com/Audumla/AUDiaGentic/commit/89062100701b90a419907c04a697d176c2799e4b))
* remove stale manifest.py references, update component marker docs ([56d6bbf](https://github.com/Audumla/AUDiaGentic/commit/56d6bbfb6dbe777bc61aced1bfbcb8f7c5d46084))
* rewrite agent system prompt with full MCP tool surface and constraints ([caa462b](https://github.com/Audumla/AUDiaGentic/commit/caa462b9ced061eae6c3854388763ab7f9a533b6))
* update agent instruction files for config path rename and source-control doctrine ([3405c4a](https://github.com/Audumla/AUDiaGentic/commit/3405c4a2bf1653cf76a7020dcdd5c9413a27beb4))
