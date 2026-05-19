# Changelog

## [0.1.2](https://github.com/Audumla/AUDiaGentic/compare/v0.1.1...v0.1.2) (2026-05-19)


### Features

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
* provider lifecycle — install/uninstall, enable/disable, surface maintenance ([c8de3f8](https://github.com/Audumla/AUDiaGentic/commit/c8de3f88131bf34ab80c7d049d711e83e75594bb))
* reconcile_provider — auto-sync providers.yaml with host CLI state ([b27010c](https://github.com/Audumla/AUDiaGentic/commit/b27010cae83d8a4b58ab353778ca92aeb60a046f))
* suppress providers MCP tool call display in Pi TUI ([792d30d](https://github.com/Audumla/AUDiaGentic/commit/792d30d14cd02819d537d9e0190d90c11bb0635f))
* surface install_method from descriptor; add vscode toolchain for roo ([9148cb5](https://github.com/Audumla/AUDiaGentic/commit/9148cb575a559d47c6826cadea694363cc16a75e))
* tighten agent scope boundary, decline all off-topic requests ([c503224](https://github.com/Audumla/AUDiaGentic/commit/c503224bbbeaa204ad7148dd90f9fc83f94b8bba))


### Bug Fixes

* correct copilot install recipe from npm to gh-extension ([c7b4208](https://github.com/Audumla/AUDiaGentic/commit/c7b4208c97778c44b8bbb3465f26aa8bfd2c96c7))
* correct release component detection path in project_server ([af59efa](https://github.com/Audumla/AUDiaGentic/commit/af59efaf149f1b60e733e6329cdade2e7362202e))
* correct VS Code extension IDs and rewrite detection to use filesystem ([83891d8](https://github.com/Audumla/AUDiaGentic/commit/83891d8c57d48ed5662f19f0523901ff7730d8e6))
* graceful self-update on Windows frozen exe via detached installer ([c789aab](https://github.com/Audumla/AUDiaGentic/commit/c789aab1158c5be4d9c49669e70ce7ace5e76006))
* pass --alias &lt;profile-name&gt; to llama-server so /v1/models returns configured ID ([63bb36d](https://github.com/Audumla/AUDiaGentic/commit/63bb36d8a861a8dab18df8bc347f576df97c9b6f))
* patch MCP OAuth callback server to bind 127.0.0.1 instead of localhost ([e033165](https://github.com/Audumla/AUDiaGentic/commit/e033165ed409aa3df6e603ac891857f56c6c83d3))
* pi_args reference missed in rename, use agent_args ([7acdcd6](https://github.com/Audumla/AUDiaGentic/commit/7acdcd69d6f7c1f463cc81c6ec887ac00026b5ee))
* prevent VS Code launch during reconcile ([c027ef8](https://github.com/Audumla/AUDiaGentic/commit/c027ef86fa139390f38551331ae31bf1d68e62ed))
* provider update ([e4c53b7](https://github.com/Audumla/AUDiaGentic/commit/e4c53b747481b0c4b7e65571343c09c64f145cb1))
* reap orphan llama-server processes before starting a fresh rig ([03c7ed0](https://github.com/Audumla/AUDiaGentic/commit/03c7ed004065453586e4c763864655a59b6601f9))
* release-test wheel install, MCP project-root isolation, release-bootstrap CLI ([0d62b48](https://github.com/Audumla/AUDiaGentic/commit/0d62b4881fb0ba3f15e425625a5e0e3df7d5ce0b))
* remove extra templates/ nesting, path was templates/templates/home ([2fea2ce](https://github.com/Audumla/AUDiaGentic/commit/2fea2ced35982cc06b44f2bb898a12ef5724f5f9))
* replace null with empty defaults in providers MCP tool responses ([e8edbf2](https://github.com/Audumla/AUDiaGentic/commit/e8edbf2fd7e88455221a012f310e91acb246b737))
* resolve Docker collection error in component lifecycle tests ([e9dc7e3](https://github.com/Audumla/AUDiaGentic/commit/e9dc7e3d3756c4007da80cd952779bbf64200407))
* roo probe checks extension install; reconcile corrects stale enabled state ([f2cf8c7](https://github.com/Audumla/AUDiaGentic/commit/f2cf8c73121caa52043288609220a60304d767dc))
* seed install-mode/access-mode when reconcile enables a new provider ([e46cb3d](https://github.com/Audumla/AUDiaGentic/commit/e46cb3d528c263258f80ecd33b90af5cd2f97a20))
* suppress Pi self-version-check notification, update scaffold test paths ([9257318](https://github.com/Audumla/AUDiaGentic/commit/9257318d08cfc87e27104144c97622c6696fb8c3))
* surface components use actual surface files as detection markers ([fa8ed68](https://github.com/Audumla/AUDiaGentic/commit/fa8ed682af29e31feb65f95a617762d13c719877))
* three update/OAuth bugs found in live testing ([0e1219a](https://github.com/Audumla/AUDiaGentic/commit/0e1219ac2845f1d91a5040022669be3b8971aac2))
* update copilot to npm install; add per-provider command tests ([0c5d8ab](https://github.com/Audumla/AUDiaGentic/commit/0c5d8abb409387b181d87205e09b032713fb2004))
* updated llamacpp ([27fa33b](https://github.com/Audumla/AUDiaGentic/commit/27fa33b137c7302e1c72f12fea959504cc073f64))


### Documentation

* relax scope boundary - help/ambiguous requests explain capabilities ([8906210](https://github.com/Audumla/AUDiaGentic/commit/89062100701b90a419907c04a697d176c2799e4b))
* remove stale manifest.py references, update component marker docs ([56d6bbf](https://github.com/Audumla/AUDiaGentic/commit/56d6bbfb6dbe777bc61aced1bfbcb8f7c5d46084))
* rewrite agent system prompt with full MCP tool surface and constraints ([caa462b](https://github.com/Audumla/AUDiaGentic/commit/caa462b9ced061eae6c3854388763ab7f9a533b6))

## [0.1.1](https://github.com/Audumla/AUDiaGentic/compare/v0.1.0...v0.1.1) (2026-05-13)


### Features

* add globally installable Pi TUI harness with config-driven runner ([aa9df6a](https://github.com/Audumla/AUDiaGentic/commit/aa9df6acdbd3a15ac079a584f1b940f07c4b0ed4))
* add project, planning, and providers MCP component servers ([2d1b184](https://github.com/Audumla/AUDiaGentic/commit/2d1b184fcf17db9eb2c6ec02983c9d04f1a2dee8))
* add release-please workflow and fix wheel package-data ([47b417c](https://github.com/Audumla/AUDiaGentic/commit/47b417c0d07ff8e73b9feb69eeab8ddcfbe91c58))
* clear terminal before launching Pi harness ([ebc89c9](https://github.com/Audumla/AUDiaGentic/commit/ebc89c9d10a8bbf581ea8c86cdcdf58f8adb21b5))
* hide Pi footer via extension ([e1f843e](https://github.com/Audumla/AUDiaGentic/commit/e1f843eba51dccf4ac5d1c65a6d4d021b38adf6f))
* **knowledge:** add lifecycle query API, fuzzy search, unit tests ([ad6c95a](https://github.com/Audumla/AUDiaGentic/commit/ad6c95a9a63330b0b645232aebbeca57557f0bfa))
* **planning:** add tm_docs op=config for agent config discovery ([f21da67](https://github.com/Audumla/AUDiaGentic/commit/f21da67eae7025f85c1ac2337c9c141eb6fb6bf2))
* **planning:** canonical filename reconciliation + clean_indexes op ([383d724](https://github.com/Audumla/AUDiaGentic/commit/383d7243bd62666d0c725f72d1fac08a0361f1ce))
* **planning:** create plan-0004 and 6 tasks for knowledge proposal upgrade ([de43cfc](https://github.com/Audumla/AUDiaGentic/commit/de43cfc6bf4bb0545490a9f7d1bce3dacce5f8d7))
* **providers:** implement completion tests, JSON extraction, and loading validation for PKT-PRV-056 ([cc5da85](https://github.com/Audumla/AUDiaGentic/commit/cc5da8596874d3b1461eec7224e46d8c39c1eca5))
* release-please module, Pi lockdown, harness restructure ([7aa41ec](https://github.com/Audumla/AUDiaGentic/commit/7aa41ecf0a38703d7d3563528b2141e5113b9c8b))
* rename Pi internals to AudiaGentic, harness cli dir ([981a7f5](https://github.com/Audumla/AUDiaGentic/commit/981a7f5900db0f7052c247c1a6de2eb24cf4efee))


### Bug Fixes

* flatten harness layout and drop pi/tui dir noise ([50490d0](https://github.com/Audumla/AUDiaGentic/commit/50490d088cafb705cd2732f58ccb7fc88bd0959a))
* load footer extension explicitly instead of via settings.json ([3a2fb88](https://github.com/Audumla/AUDiaGentic/commit/3a2fb883f78c9d24b869973386468db704810fab))
* migrate Pi npm package from mariozechner to earendil-works scope ([7ab5911](https://github.com/Audumla/AUDiaGentic/commit/7ab5911425c4709fa49bc1a885bcf2d7002ef094))
* **planning:** realign all ID counters and reconcile filenames to canonical ([8ea1412](https://github.com/Audumla/AUDiaGentic/commit/8ea1412b4955581ef397081968b7799bfa7feb39))
* **planning:** restore request slugs + create spec-29, fix task collisions ([5e6b211](https://github.com/Audumla/AUDiaGentic/commit/5e6b21192ba7a19c1cd2caa305a166bd232837ee))
* rename Pi agent dir from .pi to .audiagentic ([7a49c1a](https://github.com/Audumla/AUDiaGentic/commit/7a49c1a6f556ff4d365944ff5e276a63cb7ff0d5))
* resolve npm via shutil.which on Windows and drop .audiagentic-dev gitignore ([ac8bf52](https://github.com/Audumla/AUDiaGentic/commit/ac8bf52ec943edf36dd51393cf2b96bdbd0a44f9))
* suppress Pi and harness startup output by default ([8762d67](https://github.com/Audumla/AUDiaGentic/commit/8762d67c5bfec82919b9afe7a739d148a172150d))
* use session_start event to hide footer, not ready ([3902177](https://github.com/Audumla/AUDiaGentic/commit/390217798b500a789d26be5951b6afcc750c9323))


### Documentation

* Add comprehensive v3 migration report ([28cbe1c](https://github.com/Audumla/AUDiaGentic/commit/28cbe1c9313f61e718c1081502b98a13bba4ad5d))
* add per-slice baselines to phase 0.3 migration template ([8ae9f0b](https://github.com/Audumla/AUDiaGentic/commit/8ae9f0ba64af6c107ae2a776adc9b3c7f2f8d941))
* add phase 0.3 execution guardrails addendum ([712423e](https://github.com/Audumla/AUDiaGentic/commit/712423ee740363154c0ae7c846475e708312f069))
* add phase 0.3 repository realignment view ([9bd457b](https://github.com/Audumla/AUDiaGentic/commit/9bd457baff68f2aee099b574d6519d1ac40b2dcf))
* add phase 0.3 repository-domain dependency addendum ([ce03d02](https://github.com/Audumla/AUDiaGentic/commit/ce03d02d0a8828c2668e6ac85146050680e32c15))
* add terminology capture to phase 0.3 ambiguity template ([116fe62](https://github.com/Audumla/AUDiaGentic/commit/116fe62ad8a341daef8ee4ec2820c7a52a60f298))
* align opencode provider docs with canonical tags ([2d5a857](https://github.com/Audumla/AUDiaGentic/commit/2d5a8570af451797ed8aa6d124d011d0eb27f037))
* align ownership map with frozen phase 0.3 domains ([4f3d52e](https://github.com/Audumla/AUDiaGentic/commit/4f3d52ebde75c306fb8b69cab98a11a223066c65))
* align target tree with frozen phase 0.3 domains ([cf43f21](https://github.com/Audumla/AUDiaGentic/commit/cf43f21f26553470c4311b8c123180ff3fd439f4))
* apply phase 0.3 ambiguity decisions for execution and streaming ([55a48d5](https://github.com/Audumla/AUDiaGentic/commit/55a48d5afe1862e1e213225d836a10101ae39599))
* archive superseded pre-ACP provider and overlay line ([7b947e5](https://github.com/Audumla/AUDiaGentic/commit/7b947e59d4c0cc4364af023eeeb25e84df264003))
* archive superseded pre-ACP provider and overlay line ([a3aa9f3](https://github.com/Audumla/AUDiaGentic/commit/a3aa9f3340e96dcc346debdc152f08e002820d27))
* freeze session input adapter decision for phase 0.3 ([a586116](https://github.com/Audumla/AUDiaGentic/commit/a5861167835c838815d8be0dd31d7452d791422c))
* **planning:** flesh out request-15 knowledge component improvements ([d718506](https://github.com/Audumla/AUDiaGentic/commit/d718506b5c7b64d4446571dbc1445f95394aee88))
* seed phase 0.3 ambiguity report ([b31dd9d](https://github.com/Audumla/AUDiaGentic/commit/b31dd9dbbd30491f532994de2ab68515c0b339dc))
* seed phase 0.3 migration map ([a1162f6](https://github.com/Audumla/AUDiaGentic/commit/a1162f6f1e2d8c2e59268da8f97fbc2b3891c302))
* seed phase 0.3 public import surface ([be68117](https://github.com/Audumla/AUDiaGentic/commit/be68117ca5e4cf48414b0b90c1ecd8503c54c275))
* seed phase 0.3 repository inventory ([78327e0](https://github.com/Audumla/AUDiaGentic/commit/78327e00656a98a0a96ab803ef3f8c6658aaca28))

## Changelog
