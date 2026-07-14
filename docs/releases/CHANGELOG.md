# Changelog

## [0.2.0](https://github.com/Audumla/AUDiaGentic/compare/v0.1.1...v0.2.0) (2026-07-14)


### Features

* add audiagentic refresh CLI and refresh_harness_config MCP tool ([fcac296](https://github.com/Audumla/AUDiaGentic/commit/fcac296dd95f2db283c01b552509c266f5bbb9fe))
* add description/url metadata to all provider descriptors; reconcile on launch ([f588fc6](https://github.com/Audumla/AUDiaGentic/commit/f588fc6bb1c7ef885272c5c52da54449d7638f24))
* add globally installable Pi TUI harness with config-driven runner ([0f41495](https://github.com/Audumla/AUDiaGentic/commit/0f41495b0637e545e61399f865f63a735ac93ec2))
* add LSP code actions, formatting, and organize imports ([c2d2caa](https://github.com/Audumla/AUDiaGentic/commit/c2d2caa3ab775c3627ed9f500e20a8d89991c075))
* add LSP routing policy for provider-to-LSP dispatch ([b03c73e](https://github.com/Audumla/AUDiaGentic/commit/b03c73ef5b00f26725990801591a334b8bcd1e0e))
* add markdown and YAML language support to coding-lsp ([1f43150](https://github.com/Audumla/AUDiaGentic/commit/1f431507402c301fcc83f4428a715c3de7f1093b))
* add project, planning, and providers MCP component servers ([9ee1dc7](https://github.com/Audumla/AUDiaGentic/commit/9ee1dc7b46e6e402813732e45edef646b0a5ec8f))
* add provider model catalog fetching ([ffb8adb](https://github.com/Audumla/AUDiaGentic/commit/ffb8adb2766a45f23631e034f2d0c95a726c4da4))
* add release documents and new component files ([7920e2f](https://github.com/Audumla/AUDiaGentic/commit/7920e2f081d89a9a2e0375b0b68d04a8f4377242))
* add release-please workflow and fix wheel package-data ([189b6da](https://github.com/Audumla/AUDiaGentic/commit/189b6dab3e3842832b67995e8bc5d3eb268c2019))
* add startup status output to audiagentic launcher ([5f4f8dd](https://github.com/Audumla/AUDiaGentic/commit/5f4f8ddfaa4d7a6b546a6bdf59df57fc2e304f40))
* added agent profiles component with CRUD API and MCP servers ([217fcba](https://github.com/Audumla/AUDiaGentic/commit/217fcbaf29efc9ffdc6d1f38f2b816887ba89866))
* added JSON, TOML, and Makefile language support to coding-lsp ([e03389e](https://github.com/Audumla/AUDiaGentic/commit/e03389eff4326cb0bb42dbeb2dde163e4a80fef8))
* added memory component with swappable backends + provisioning consumers ([9ffed76](https://github.com/Audumla/AUDiaGentic/commit/9ffed766c850ae31ab1594f05f13627833609572))
* **agent-jobs:** core updates - prompt system, job records, state machine ([e800920](https://github.com/Audumla/AUDiaGentic/commit/e8009204b6f6a1e36d0e3d5a862f1c56d9f9e68d))
* **agent-jobs:** event-driven jobs infrastructure ([01dd26e](https://github.com/Audumla/AUDiaGentic/commit/01dd26e97695eb38127dddd04cb9d3d3b1796240))
* **agents:** gateway cancel propagation and event improvements ([8fa8cae](https://github.com/Audumla/AUDiaGentic/commit/8fa8cae33034945957ba926dfbb4e9512015f94b))
* audiagentic component CLI + release wheel test ([c68eaa3](https://github.com/Audumla/AUDiaGentic/commit/c68eaa3bb466ecaccd43c57553f75496d4208c92))
* check in all 6 change groups for current release ([0f62777](https://github.com/Audumla/AUDiaGentic/commit/0f62777daa1cac734c230619a120161254c03557))
* clear terminal before launching Pi harness ([54f326a](https://github.com/Audumla/AUDiaGentic/commit/54f326a75947660b6ba904c91e72d65abce2ef5f))
* component profiles, interaction primitives, memory config status, event bus hardening, antigravity provider ([f0e2f36](https://github.com/Audumla/AUDiaGentic/commit/f0e2f36d3f5517444227af299dd4685e4bf78ed9))
* core infrastructure — foundation, runtime, ledger, session, planning, release-please ([15ec7f2](https://github.com/Audumla/AUDiaGentic/commit/15ec7f2ea8a83d7b24d1620f8d80011beda1e1e0))
* default model to qwen3.5-2b-q4_k_s ([1ebcc45](https://github.com/Audumla/AUDiaGentic/commit/1ebcc459a982b9cbb94a9c43fa8ce4f7e0ad0787))
* enable MCP, disable builtin tools, block all slash commands ([faca320](https://github.com/Audumla/AUDiaGentic/commit/faca32012c61ed8a50a6e18fbd87a49e5c5337a6))
* fetch model catalog on provider first enable ([afc5c6e](https://github.com/Audumla/AUDiaGentic/commit/afc5c6ea4d01e77c0c14312a4dc7e12d03007098))
* generic config-completeness derivation for any component (chg_20260701_022015, chg_20260701_023038) ([c69164d](https://github.com/Audumla/AUDiaGentic/commit/c69164d8745d8756a4ba30d76d09f14dc8dd994d))
* Go toolchain in Docker test-base + make-ls auto-install validation ([7efc58b](https://github.com/Audumla/AUDiaGentic/commit/7efc58b05d4e3281a1fce368435fa04b027bbacb))
* harness-scoped components + auto-update subsystem ([864dcf0](https://github.com/Audumla/AUDiaGentic/commit/864dcf007e24ad2f07cec91b0c167da88e59d4b6))
* **harness:** auto-reload Pi session after reload_required MCP tool result ([1bb5f6d](https://github.com/Audumla/AUDiaGentic/commit/1bb5f6d45d5870713e4d2ec0da4169df16e0bde5))
* hide audiagentic_ MCP tool call blocks in Pi TUI ([c5f8b42](https://github.com/Audumla/AUDiaGentic/commit/c5f8b42ea21c559f1897aa74444f9eedfc064e38))
* hide Pi footer via extension ([e5058f2](https://github.com/Audumla/AUDiaGentic/commit/e5058f266ad1d1f3207a64ea4bedd363c24d684a))
* hide thinking block in agent UI ([bf34c76](https://github.com/Audumla/AUDiaGentic/commit/bf34c7604257e589fe9080eefe1adcec1904712c))
* include VS Code extension status in list_providers and provider_status ([a973204](https://github.com/Audumla/AUDiaGentic/commit/a97320420026a349e33a4bccdf44537c9872b29a))
* **knowledge:** add lifecycle query API, fuzzy search, unit tests ([5bad09e](https://github.com/Audumla/AUDiaGentic/commit/5bad09e11fa44d45cbe9b1c2635d893b6c52b736))
* ledger-git linkage, release flow fixes, probe field, config-driven MCP names ([630d66d](https://github.com/Audumla/AUDiaGentic/commit/630d66dc7e8678656f3c88c5e318267e62bbfe08))
* **logging:** add centralized logging package ([595260f](https://github.com/Audumla/AUDiaGentic/commit/595260fd1d746b5ea2facbded92d619f0a204ba6))
* **logging:** add console format for user-facing output ([a651f5f](https://github.com/Audumla/AUDiaGentic/commit/a651f5fa16c81c4b25bbdc1fbdc59d94f6d2568c))
* LSP auto-install missing servers + skip broken servers ([1b965df](https://github.com/Audumla/AUDiaGentic/commit/1b965df9da214c689c2c2803d07d1cbce025c6c3))
* **mcp:** add log_tool_call decorator and instrument all MCP tool functions ([ff1b30c](https://github.com/Audumla/AUDiaGentic/commit/ff1b30c65ad53327375b8d9b40042bda710f95f5))
* **mcp:** add new modular MCP entry points ([5aa7031](https://github.com/Audumla/AUDiaGentic/commit/5aa7031a49983ad3597074348202a85bf757bfaa))
* **memory:** complete RecipeSpec config-driven recipe framework ([beb6766](https://github.com/Audumla/AUDiaGentic/commit/beb676640899cbd49f1e04fea4fd27197e6e1dcf))
* migrate to workflow-based CLI provisioning and reorganize components ([50c36d6](https://github.com/Audumla/AUDiaGentic/commit/50c36d638787de8adf3eb89c2be19b32123d5662))
* **planning:** add tm_docs op=config for agent config discovery ([705b7b8](https://github.com/Audumla/AUDiaGentic/commit/705b7b8349adda4c35002e17d2109219dfed329b))
* **planning:** canonical filename reconciliation + clean_indexes op ([707d6cb](https://github.com/Audumla/AUDiaGentic/commit/707d6cb66d2c40c94eca44bfacf30deb46402de2))
* **planning:** create plan-0004 and 6 tasks for knowledge proposal upgrade ([16269f2](https://github.com/Audumla/AUDiaGentic/commit/16269f2afe623ef87643228f65ea402f899b5e03))
* **project-server:** surface source-control availability and warnings on install ([5c504ac](https://github.com/Audumla/AUDiaGentic/commit/5c504ac3343ffc0ba8fac52572b39e6242f573da))
* provider lifecycle — install/uninstall, enable/disable, surface maintenance ([0d989fc](https://github.com/Audumla/AUDiaGentic/commit/0d989fcaeaf004a12762b53408e0bf215cfd83df))
* **providers:** harness descriptor and callable config_path support ([a41c47b](https://github.com/Audumla/AUDiaGentic/commit/a41c47bcdcfbdf6ab94777ecb9995757afd3f5c8))
* provisioning-recipe foundation with shared install/uninstall primitives ([8df2541](https://github.com/Audumla/AUDiaGentic/commit/8df254115a4f4ba8f34080594b67da68663225ec))
* reconcile_provider — auto-sync providers.yaml with host CLI state ([b000de4](https://github.com/Audumla/AUDiaGentic/commit/b000de486219d4bf4e5e61a95568ebdddd40722f))
* release-please module, Pi lockdown, harness restructure ([f2ab7fb](https://github.com/Audumla/AUDiaGentic/commit/f2ab7fb024ec801a5a1918ecb88a061c2f220755))
* rename Pi internals to AudiaGentic, harness cli dir ([b815116](https://github.com/Audumla/AUDiaGentic/commit/b815116bc65bff7555b65c3336b7a44ed8e4c63b))
* **session:** add update_global_embedded_rig tool ([cbad429](https://github.com/Audumla/AUDiaGentic/commit/cbad4298acec23279df92fe57697f9dd63af86ee))
* **source-control:** two-step dependency installer for git/gh/gh-mcp/uv ([49a0d1c](https://github.com/Audumla/AUDiaGentic/commit/49a0d1cc3970bb32de1ea207cae7661c60781905))
* suppress providers MCP tool call display in Pi TUI ([b047a2a](https://github.com/Audumla/AUDiaGentic/commit/b047a2a52996d888fb01a8f9b665271ad09cc67c))
* surface install_method from descriptor; add vscode toolchain for roo ([cbbab58](https://github.com/Audumla/AUDiaGentic/commit/cbbab582b74b866b1565c9cc893f0dfd5b692405))
* tighten agent scope boundary, decline all off-topic requests ([294de22](https://github.com/Audumla/AUDiaGentic/commit/294de22603bf6d27280aab315a96eab267a0e537))


### Bug Fixes

* align harness tool names with MCP declarations and fix run_agent signature ([6658ac8](https://github.com/Audumla/AUDiaGentic/commit/6658ac8a00ace9573b72434808725091aa9f485b))
* **CC05, ML04:** mark flat-component regression verification done ([3285f66](https://github.com/Audumla/AUDiaGentic/commit/3285f661d9b844290eb06e103cce93b734f66ec2))
* **CC06:** delete dead EventService and ReplayService — zero external importers ([8d9ee3b](https://github.com/Audumla/AUDiaGentic/commit/8d9ee3b187d387c6dbeb1fd525b4db1099bd24a9))
* **CC06:** delete dead EventService and ReplayService — zero importers, update __init__.py and README ([a8cfd4e](https://github.com/Audumla/AUDiaGentic/commit/a8cfd4ea658e55b48889668be52ababf530f3840))
* **CC06:** update risk assessment after failed deletion — public API export ([0234019](https://github.com/Audumla/AUDiaGentic/commit/0234019c13fec35c23634861045a5c15aebeb91b))
* **CC10:** register all 62 missing error resolutions — foundation, project, rig, harness, providers ([2b9c7d0](https://github.com/Audumla/AUDiaGentic/commit/2b9c7d069394244efe33c643037416b365316adc))
* **CC10:** register foundation, project, rig error resolutions (10/62) ([357912e](https://github.com/Audumla/AUDiaGentic/commit/357912e8bc0aa45acada38441022f10acea375cb))
* **CC10:** register harness error resolutions (22/62) ([1dfe863](https://github.com/Audumla/AUDiaGentic/commit/1dfe863a574ab49687f017ca313de4977e90a24d))
* code cleanup pass 4 — 7 items (Std 1/5/8/9) ([ff562ee](https://github.com/Audumla/AUDiaGentic/commit/ff562ee86f0f77a7b78dfc67ba99d5cebebfe8c4))
* Codex adapter MCP config handling, harness event registration ([2836e65](https://github.com/Audumla/AUDiaGentic/commit/2836e6544b6c4fb0325e52fe321a12c5a07e4e6c))
* coding-lsp status hook alias + UTF-8-safe probe decoding ([c89576b](https://github.com/Audumla/AUDiaGentic/commit/c89576b5babc5ede84b97f791b6cffba8d169b78))
* correct copilot install recipe from npm to gh-extension ([05bbd46](https://github.com/Audumla/AUDiaGentic/commit/05bbd46928a746fc9d059da9bfe616adf179908b))
* correct error-handling defects from audit ([f20939a](https://github.com/Audumla/AUDiaGentic/commit/f20939a9e65a98d6c623111fd38d92153c55a893))
* correct release component detection path in project_server ([ea3f4d1](https://github.com/Audumla/AUDiaGentic/commit/ea3f4d1e369ef9c33228bd4d75923a7d198af91b))
* correct VS Code extension IDs and rewrite detection to use filesystem ([bfbd16c](https://github.com/Audumla/AUDiaGentic/commit/bfbd16c0e376ea66453464cbbfb5c7fa019dfec9))
* finalize circular import resolution, add subprocess timeouts for rig cleanup ([9aaab09](https://github.com/Audumla/AUDiaGentic/commit/9aaab095248ffd185fbc8bd3485044ea93582b8a))
* finalize source control, propagation, and remaining tests ([623a5dc](https://github.com/Audumla/AUDiaGentic/commit/623a5dc7dd3c00c19d1059b7b219470ca3e5c489))
* flatten harness layout and drop pi/tui dir noise ([dffa893](https://github.com/Audumla/AUDiaGentic/commit/dffa893ac65e1c732553b888f9f64a5b5e34beb4))
* **foundation:** register VAL-FDESC error resolutions for agent-facing guidance ([d8ab994](https://github.com/Audumla/AUDiaGentic/commit/d8ab9941d251484d622b635b3c1fb5f922e8fab0))
* graceful self-update on Windows frozen exe via detached installer ([ed9322f](https://github.com/Audumla/AUDiaGentic/commit/ed9322f2d8cc644967291eb924a60f9cbeb426f6))
* **install:** use regex to match pi update-check blocks regardless of variable names ([37736cb](https://github.com/Audumla/AUDiaGentic/commit/37736cbefb028d55ce9f3fceb1f3fc3d99aa01e5))
* kill orphaned MCP/LSP child processes when agent host exits ([1850310](https://github.com/Audumla/AUDiaGentic/commit/1850310f55b9675c5db3774f882bac09ddcfada5))
* load footer extension explicitly instead of via settings.json ([c13b17a](https://github.com/Audumla/AUDiaGentic/commit/c13b17ab3b0e2037079b6bc3b8dabaa3101cd571))
* **logging,install:** suppress console log output and fix npm two-step install ([7ed64e9](https://github.com/Audumla/AUDiaGentic/commit/7ed64e9dc062e631aa2f6dbe6f08f6338744672d))
* **logging:** apply exc_info=True and logger standards across codebase ([55c43a9](https://github.com/Audumla/AUDiaGentic/commit/55c43a9eced60f54138405b523b222a63c212af6))
* MCP elicitation, profile resolution, test isolation, provider surfaces, Hindsight teardown, portable python placeholder ([246171f](https://github.com/Audumla/AUDiaGentic/commit/246171f879c9f0cf9aaaece3aecc5b38d2b91c4e))
* MCP servers launch without console windows + project config to all providers ([1711b26](https://github.com/Audumla/AUDiaGentic/commit/1711b26c121bf8d20e9f72e7649f32a11793665d))
* migrate Pi npm package from mariozechner to earendil-works scope ([1bbebd7](https://github.com/Audumla/AUDiaGentic/commit/1bbebd7aea3d7f0aabc489642669e39d625b881d))
* pass --alias &lt;profile-name&gt; to llama-server so /v1/models returns configured ID ([262a86d](https://github.com/Audumla/AUDiaGentic/commit/262a86d9dbcb162d485fefcf47ddb513d04c9a6c))
* patch MCP OAuth callback server to bind 127.0.0.1 instead of localhost ([75ade0e](https://github.com/Audumla/AUDiaGentic/commit/75ade0e8a98a9cbbbcb09711a0b624598149cca3))
* pi_args reference missed in rename, use agent_args ([2445876](https://github.com/Audumla/AUDiaGentic/commit/2445876cb32d4c676e9cdaeadb3d3f4307af00af))
* **planning:** realign all ID counters and reconcile filenames to canonical ([6eb4073](https://github.com/Audumla/AUDiaGentic/commit/6eb4073fa9a498bd0c266661eb3552eecc5591a1))
* **planning:** restore request slugs + create spec-29, fix task collisions ([f789c7e](https://github.com/Audumla/AUDiaGentic/commit/f789c7e18f1b376c439bb396ac2d5e124d95b628))
* **plans:** add complexity ranking to all active items (6 simple, 8 mid, 8 complex) ([cbc7ab5](https://github.com/Audumla/AUDiaGentic/commit/cbc7ab5ccbb92d1284e8f3025bb5ea2b2dfacec4))
* **plans:** add deferred items and execution order to plan indexes ([773dbd0](https://github.com/Audumla/AUDiaGentic/commit/773dbd0df64a054724f8671b3be2971b52bf3366))
* **plans:** add missing detail to ML items, create LSP plan context, add cross-references ([d1ca720](https://github.com/Audumla/AUDiaGentic/commit/d1ca720d1761b76b24fa743fdb5cda42aa482753))
* **plans:** add validate-first field to all active items, create TEMPLATE_ITEM.md ([6a36676](https://github.com/Audumla/AUDiaGentic/commit/6a36676311839dd143037fc13faee445d0d1b606))
* **plans:** restore original plan IDs in completed items (plan-code-cleanup, plan-refactor-round2, plan-lsp-mcp-enhancement, plan-multilayer-component) ([6c8384f](https://github.com/Audumla/AUDiaGentic/commit/6c8384f96b9010cbbcaeb9464a9716e1cee0f842))
* **plans:** restore plan ID for CC01 — keep plan-code-cleanup for both active and completed ([226f747](https://github.com/Audumla/AUDiaGentic/commit/226f747586c949f6a2e8a1a1eece992fd31f6c22))
* **plans:** update item states to reflect actual completion (23 done, 16 not_done) ([60e2293](https://github.com/Audumla/AUDiaGentic/commit/60e22932c64ddd4a39544c11dd642fb8d68daeee))
* prevent VS Code launch during reconcile ([f0fd412](https://github.com/Audumla/AUDiaGentic/commit/f0fd4123df7dce4f28168b9f6941694001aba304))
* **project-server:** regenerate mcp.json after component state changes via MCP tools ([190f732](https://github.com/Audumla/AUDiaGentic/commit/190f732473bece464defdb249ee50f5f7b26414c))
* provider cleanup ([771a6ec](https://github.com/Audumla/AUDiaGentic/commit/771a6ece0d1afb881d42750a3252a685b25ed37f))
* provider update ([4375707](https://github.com/Audumla/AUDiaGentic/commit/4375707b82d84694453d500620dcd01f56bed599))
* **providers:** fix stale API references and missing StateMachine config ([b83aa04](https://github.com/Audumla/AUDiaGentic/commit/b83aa0435d8e56b9d377aa235fb2e142089eac59))
* **providers:** probe CLIs via shell so Windows .CMD shims resolve ([4d737da](https://github.com/Audumla/AUDiaGentic/commit/4d737da62b77e926da8ad5d112d1067d288bdfc8))
* **providers:** resolve CLI binary path before subprocess in probe ([b682291](https://github.com/Audumla/AUDiaGentic/commit/b682291764d8f547303118b6b18c73e8f91d423f))
* **R2B3:** investigate complete — leave harness MCP config trio as-is (structural duplication) ([5a4e7da](https://github.com/Audumla/AUDiaGentic/commit/5a4e7da7dd1a5a184a6d5dddc98f54c2ecf873d1))
* read AGENT_VERSION from package instead of hardcoded PI version ([8588cc3](https://github.com/Audumla/AUDiaGentic/commit/8588cc3a39943032e0f5ac42c6269b85b683ac96))
* reap orphan llama-server processes before starting a fresh rig ([36d36ed](https://github.com/Audumla/AUDiaGentic/commit/36d36ed3f4bce4f54900a62172492a33fc7f1b9d))
* release-test wheel install, MCP project-root isolation, release-bootstrap CLI ([c83ed92](https://github.com/Audumla/AUDiaGentic/commit/c83ed9293e27b572b4f6863caf171087c83a2b80))
* **release:** lock pre-1.0 version policy ([1e49cfd](https://github.com/Audumla/AUDiaGentic/commit/1e49cfd95b566405502d45946a6dc171fe881bcd))
* remove extra templates/ nesting, path was templates/templates/home ([78cf198](https://github.com/Audumla/AUDiaGentic/commit/78cf198dce10f84c55a1f2e7283ca7bb30221451))
* rename Pi agent dir from .pi to .audiagentic ([ef847e4](https://github.com/Audumla/AUDiaGentic/commit/ef847e4a339cf2631807d10b89b30eef84ad16f3))
* replace null with empty defaults in providers MCP tool responses ([74d855e](https://github.com/Audumla/AUDiaGentic/commit/74d855ec8c5ecca6be76c52660330a075a0ecdda))
* resolve circular import in path resolution, wire new commands in launcher ([c43c71f](https://github.com/Audumla/AUDiaGentic/commit/c43c71f3e5acb8690802ed7466e2135c51588450))
* resolve Docker collection error in component lifecycle tests ([45214f8](https://github.com/Audumla/AUDiaGentic/commit/45214f8cc15666a8e30974073bb30d31a11c4217))
* resolve npm via shutil.which on Windows and drop .audiagentic-dev gitignore ([e57f511](https://github.com/Audumla/AUDiaGentic/commit/e57f511eeb9b864eb699d4192db0d6b699a6ba45))
* restore required ag-review prompt asset and update test count ([6bb002f](https://github.com/Audumla/AUDiaGentic/commit/6bb002f187857a1c71a4725b6bc2850ea984f46d))
* rewrite GitHub OAuth device flow auth - non-blocking start/poll, env token fallback ([75eeb65](https://github.com/Audumla/AUDiaGentic/commit/75eeb65022dc10cb63e9f80f5a1ddf0a3f5e77da))
* roo probe checks extension install; reconcile corrects stale enabled state ([1698cc4](https://github.com/Audumla/AUDiaGentic/commit/1698cc4a3b9b9d3e08b107dbe7039f7b16ca8586))
* Rust-analyzer e2e LSP test suite — all 68 tests passing ([88a91f2](https://github.com/Audumla/AUDiaGentic/commit/88a91f2eee89d33355094e909b338abd1258e115))
* seed install-mode/access-mode when reconcile enables a new provider ([6a810bf](https://github.com/Audumla/AUDiaGentic/commit/6a810bfca865d9fb7a1a641f47b770096af9382f))
* **SL02:** add DescriptorType enum for typed YAML dispatch ([2385693](https://github.com/Audumla/AUDiaGentic/commit/23856935b8bb8602f062c47be63fc505465c5ae5))
* **SL02:** add DescriptorType enum for typed YAML dispatch; update R2B2 (done), R2B3 (leave as-is) ([b577c77](https://github.com/Audumla/AUDiaGentic/commit/b577c77d6367e8aaf57be8a233095cae14875ce1))
* **source-control:** eliminate blocking gh probe and per-call availability checks ([7c10a45](https://github.com/Audumla/AUDiaGentic/commit/7c10a45d6284fffa50072459ee9681e32cd0bf5b))
* **source-control:** post-commit hook shebang placement caused Exec format error ([9438b7b](https://github.com/Audumla/AUDiaGentic/commit/9438b7b82a09a32f0898be9e11570f11cebe2b35))
* suppress Pi and harness startup output by default ([df8a9dd](https://github.com/Audumla/AUDiaGentic/commit/df8a9dd4694b89eb59cdeb8151dcc41b94b547fa))
* suppress Pi self-version-check notification, update scaffold test paths ([7499afa](https://github.com/Audumla/AUDiaGentic/commit/7499afaa184defb2b5be94148c452facabd21730))
* surface components use actual surface files as detection markers ([ef27350](https://github.com/Audumla/AUDiaGentic/commit/ef273509d99ce50f52142b86b6fa03e73efd1aee))
* **tests:** correct drifted component IDs, harness-scope guards, docker coverage ([cf4c1e8](https://github.com/Audumla/AUDiaGentic/commit/cf4c1e888e4241310ac76774a350036958417adc))
* **tests:** update stale LSP diagnostics tests to pull-model API ([0a3246c](https://github.com/Audumla/AUDiaGentic/commit/0a3246ce054ceb8e5dd465d94ec04624f63f98c1))
* three update/OAuth bugs found in live testing ([cbeec2d](https://github.com/Audumla/AUDiaGentic/commit/cbeec2d40552d63b5f28296889c2d4afe9fb11bf))
* tighten dependency and provider validation ([008e6d3](https://github.com/Audumla/AUDiaGentic/commit/008e6d37c7dfe505603356e3c78b57a7748876a0))
* update copilot to npm install; add per-provider command tests ([1709383](https://github.com/Audumla/AUDiaGentic/commit/1709383791f1675e85db41ee45e5edba43237505))
* updated llamacpp ([c458245](https://github.com/Audumla/AUDiaGentic/commit/c4582453181d02172a63c27ab5a2bdd1075d48a3))
* **update:** suppress auto-prompt permanently after failed install ([6aa2e38](https://github.com/Audumla/AUDiaGentic/commit/6aa2e38b3a9899f6b92d8a461498f14efd6c43a9))
* use session_start event to hide footer, not ready ([d48649d](https://github.com/Audumla/AUDiaGentic/commit/d48649dcb6cfdd67291a77aa8d562b0dbbe8bf82))
* Windows workspace diagnostics - shell-launch batch CLIs to prevent WinError 2 ([75a340d](https://github.com/Audumla/AUDiaGentic/commit/75a340de2a0a50519107ef9c9534d430b0b78217))


### Reverts

* **CC06:** restore EventService and ReplayService — __init__.py exports them, runtime importers exist ([eba3f56](https://github.com/Audumla/AUDiaGentic/commit/eba3f562006f4e30a45635c0e6e98dcb8f4c5cf8))
* remove accidentally committed prompt file from CC10 ([360cf0f](https://github.com/Audumla/AUDiaGentic/commit/360cf0fd780402fc9451e2a65393468e9d261938))
* **SL02:** undo implementation — P3 priority, minor robustness improvement, not needed yet ([4c6ff2b](https://github.com/Audumla/AUDiaGentic/commit/4c6ff2b4fcc48d8c6f7db068cedb244d67feba0e))


### Documentation

* add arch-standards AR23 and output-redaction OU01 planning items ([f2f3c27](https://github.com/Audumla/AUDiaGentic/commit/f2f3c2701c647b4cb5268ea0d53dda309cc09a49))
* add code-cleanup items CC29-CC32 for config-driven labels ([8e41ca0](https://github.com/Audumla/AUDiaGentic/commit/8e41ca0aef8baa77e4eb43bbb65070c7d5975ed7))
* add planning items for memory-hindsight, process-lifecycle, provider-recipe-refactor, and toolchain-provisioning ([d1d72ae](https://github.com/Audumla/AUDiaGentic/commit/d1d72aef1cc2ce89a5286434d840577635a1b153))
* add READMEs and review findings standards ([a6f3ce9](https://github.com/Audumla/AUDiaGentic/commit/a6f3ce9c6e8d0d7bc6242ad62af276ec2236e179))
* additional managed-config-consistency updates and MA16 item ([c13c807](https://github.com/Audumla/AUDiaGentic/commit/c13c8077da0de92189eb73e812a2cbc1a02b5adf))
* **agents:** add agent-ledger process and ledger write instructions ([7055791](https://github.com/Audumla/AUDiaGentic/commit/7055791163b5f1c1f72b9f33b218dc588d3e0ff1))
* **agents:** update agent instruction files for all providers ([edb0e84](https://github.com/Audumla/AUDiaGentic/commit/edb0e848b2be26f0d8bbe6331371893bd3befcbb))
* archive completed plan items (AG14, AR08-AR22, CC07, CC25, CP12-CP13, EV07-EV12, FI06-FI08, HM20-HM21, PV01, SL04, SL09-SL10 and reviews) ([7d83af0](https://github.com/Audumla/AUDiaGentic/commit/7d83af0eca72a89921a647b84ae9421d5d531132))
* clean up active planning-ledger-linkage items (moved to completed) + standards update ([b69deb3](https://github.com/Audumla/AUDiaGentic/commit/b69deb342b3e07196e460e01c173ccaf926540dd))
* correct MO03 provider adapter validation gates ([9a94cb9](https://github.com/Audumla/AUDiaGentic/commit/9a94cb95d32027df7f98f18c43ac9f312849f2d5))
* extend model-endpoint-management planning with MO05-MO06, update existing items, refresh provider capabilities reference ([7b92353](https://github.com/Audumla/AUDiaGentic/commit/7b923536c029dae30cee222b16241002704ccc41))
* link MO01 refreshed reviews ([89583cf](https://github.com/Audumla/AUDiaGentic/commit/89583cf579d1517e9642e1b23dfca7c31e1ebb7d))
* link MO02 refreshed reviews ([b908b6e](https://github.com/Audumla/AUDiaGentic/commit/b908b6e4490544139842345433f20812a9bd8672))
* link MO04 refreshed review ([1432f9d](https://github.com/Audumla/AUDiaGentic/commit/1432f9d0e0e554f6f414576e0d0ecfaf72d8b973))
* link MO05 schema review ([437face](https://github.com/Audumla/AUDiaGentic/commit/437facee2e82540e2983515820ad387eb421f0b6))
* link MO06 spec extraction review ([fa92091](https://github.com/Audumla/AUDiaGentic/commit/fa92091e0c612a2a0587dcae274c22b2a3a3ef21))
* managed mutation audit, provider model endpoints, architecture & observability standards, release ledger (#ledger) ([f1de6e9](https://github.com/Audumla/AUDiaGentic/commit/f1de6e953ed271dc6eb986811d9c5c6a7e444df6))
* model-endpoint-management planning items, recipe-system-review, ([3a69771](https://github.com/Audumla/AUDiaGentic/commit/3a69771dd6d48f135f5880739bf2c6c4e0eff9c7))
* move completed plan items, add architecture assessments ([29b2a89](https://github.com/Audumla/AUDiaGentic/commit/29b2a89437dfae5208880f20b741f83b6fe2ffe0))
* move PL* items to completed, add EDJ/RS review records (planning-ledger-linkage completion) ([a896532](https://github.com/Audumla/AUDiaGentic/commit/a8965326b989c7baaf595b4bc9ea4b8afbcebe4d))
* planning items (completed arch-standards, event-driven-jobs, recipe-system-review; updated model-endpoint-management) ([cffee38](https://github.com/Audumla/AUDiaGentic/commit/cffee38c72fb4712e5cfb3daacfe47e09b0117e7))
* **planning:** archive completed event-driven-jobs and recipe-system-review items ([5013954](https://github.com/Audumla/AUDiaGentic/commit/50139548e2bcc4233e5c0e5b940fb1b5ea1b4c88))
* **planning:** flesh out request-15 knowledge component improvements ([4f81305](https://github.com/Audumla/AUDiaGentic/commit/4f8130549d6143534598e6395fe08abb556731ec))
* **planning:** model-endpoint-management, new plans, and active item updates ([eab75e4](https://github.com/Audumla/AUDiaGentic/commit/eab75e4296b325276dbb6dae2d43c21888d735fd))
* **planning:** refine EDJ01-EDJ11 event-driven job plan items ([5037967](https://github.com/Audumla/AUDiaGentic/commit/50379672340d8f7fda05c03ec18fe29e8ebfd0f6))
* **planning:** SL15 completed, EDJ reviews resolved, new cleanup items ([498d889](https://github.com/Audumla/AUDiaGentic/commit/498d889adc9b83ab8e81387d62a6cc8e919ab599))
* **planning:** unify-install-paths plan item and review ([847215e](https://github.com/Audumla/AUDiaGentic/commit/847215e8eb2d9e642f150167654ed9f0e0036ef0))
* **planning:** update UN01 unify-install-paths item ([571f34b](https://github.com/Audumla/AUDiaGentic/commit/571f34b0220dc87d0a9cb90d796d61e9e0c3969d))
* refine event-driven job plan items with schema validation & prompt context (chg_20260709_032805 + workflow entries) ([96e8f49](https://github.com/Audumla/AUDiaGentic/commit/96e8f49927011d1db8ae7444000f459f1a7f8a4b))
* refresh model endpoint capabilities against current code ([dd19de0](https://github.com/Audumla/AUDiaGentic/commit/dd19de01fcf3385edba3f14ab0f33591aed00223))
* relax scope boundary - help/ambiguous requests explain capabilities ([6e021ad](https://github.com/Audumla/AUDiaGentic/commit/6e021adf8d7ffdf822a51d80656094b3f73269fb))
* remove completed planning items from active (arch-standards, event-driven-jobs, recipe-system-review) ([586d49a](https://github.com/Audumla/AUDiaGentic/commit/586d49ae6ba5ca3330672df54c430b232a36781d))
* remove stale manifest.py references, update component marker docs ([3e67d8a](https://github.com/Audumla/AUDiaGentic/commit/3e67d8a465033ef1eaa38a62bd6fb5e820416004))
* rewrite agent system prompt with full MCP tool surface and constraints ([7feefdf](https://github.com/Audumla/AUDiaGentic/commit/7feefdfd5f19d9a837923678eaf95621ce1fd282))
* standards updates (architecture, observability), provider model endpoints, release ledger sync ([b669a93](https://github.com/Audumla/AUDiaGentic/commit/b669a933e73afece25c26534cf1a8288f7d4ce0a))
* **standards:** architecture, component creation, managed mutation audit ([0c0a6e3](https://github.com/Audumla/AUDiaGentic/commit/0c0a6e3f5ec685315ff945531f33ceaa3147614d))
* **standards:** clarify test boundaries, add recipe usage guide ([a3435ad](https://github.com/Audumla/AUDiaGentic/commit/a3435ad83ecd5c5e24eeab7508a829c42766031f))
* update agent instruction files for config path rename and source-control doctrine ([7188d6d](https://github.com/Audumla/AUDiaGentic/commit/7188d6d935322b715feaae8e6a0be7d39f4e7e15))
* update CREATING_A_COMPONENT.md for auto detection-marker behavior ([c0b9ade](https://github.com/Audumla/AUDiaGentic/commit/c0b9adef93f961e61999b739e5e9df1d517a39d9))
* update managed-config-consistency plan items MA02-MA15 with review feedback ([78bea86](https://github.com/Audumla/AUDiaGentic/commit/78bea8683d9c1f74c8734cd0038478548300328b))
* update model-endpoint plan MO01-MO15, archive UN01-UN04 unify-install-paths ([dbf99b1](https://github.com/Audumla/AUDiaGentic/commit/dbf99b1e5b210ecd0a455b0dad264ca442ccfae6))
* update release ledger with latest change events (#ledger) ([86e2dcd](https://github.com/Audumla/AUDiaGentic/commit/86e2dcd921c1a27182b5035cc03b3d7563e23a58))

## Changelog

## rel_0002
- Deduplicate streaming timestamp helper — now uses shared foundation.time
- Deduplicate MCP sync logic — one shared body, two thin wrappers
- Consolidate stub adapter bodies — 6 adapters now share 2 helpers
- Clean up 4 tiny workflow/harness files — dead code removed, small modules merged
- Split 6 large files (>400 lines) into focused modules by logical concern
- Fixed several error-handling bugs: a NameError in the updater spawn path, silent diagnostics/validation failures now logged, and cascade failures raised to warning level.
- Added regression tests covering the error-handling bug fixes so they don't reappear.
- Fixed provider CLIs (opencode and others) reporting WinError 2 on Windows by running their version probes through the shell so npm-installed .CMD shims resolve correctly.
- Verified every provider installs and runs correctly in Docker, and added a test ensuring no provider's availability check crashes or falsely reports installed when its CLI is missing.
- Slimmed the generated agent instruction files (CLAUDE.md etc.) and made them consistent across all providers, removing duplicated doctrine to cut context overhead.
- Added an update_global_embedded_rig tool to update the shared global embedded rig binaries, warning when a project-local rig overrides them.
- Added a console logging format that prints clean user-facing lines instead of raw log records.
- Tidied import ordering in coding-lsp modules and an LSP e2e test.
- Stopped tracking generated provider surfaces and operational artifacts (gitignore + untrack), and moved canonical skills to .agents/.
- Stopped tracking the generated .mcp.json (machine-local absolute paths); now gitignored.
- Refactored Claude hook handling and prompt-launch review pipeline into smaller, single-purpose modules and fixed a duplicated stdin-handling code path in the hook CLI.
- Enabling a language LSP now installs its language server automatically in one step — you just name the language (e.g. python) and the matching server binary is resolved and installed for you, with rollback if the install fails. Also fixed project-root detection to stop at your home folder so temp/working dirs no longer pick up home's LSP config.
- Consolidated duplicated _project_root() helper into single canonical implementation.
- Extracted duplicated MCP server helpers into shared component_server module.
- Split LSP API into operations and config/dependency modules for single-responsibility.
- Extracted MCP propagation logic from lifecycle components module into dedicated module.
- When the coding-lsp component is enabled, the pi agent now automatically installs the pi-lens extension, which auto-discovers your installed language servers from PATH — so enabling a language (which installs its server) just works in pi with no extra setup. pi uses pi-lens for code intelligence instead of the generic LSP bridge.
- Collapsed 9 near-identical render_contributions functions into a single factory.
- Fixed opencode language-server config: Python now correctly configures opencode's built-in 'pyright' server (and C++ its 'clangd' server) instead of creating a mismatched 'python' entry. The LSP component stays language-agnostic; the opencode adapter maps to opencode's server names internally.
- Disabling a component now removes its instruction blocks (e.g. ag-* tag doctrine) from AGENTS.md and other provider files, instead of leaving them stranded until uninstall.
- Fixed agents being told to use LSP tools (lsp_diagnostics, lsp_symbols) that aren't available to them. The LSP tool list is no longer duplicated into instruction files (AGENTS.md/CLAUDE.md/GEMINI.md); agents discover LSP tools directly from the MCP server, so only agents that actually have the LSP server see those tools.
- Managed sections in agent instruction files (AGENTS.md, CLAUDE.md, etc.) are now wrapped in a single clean region with readable `## Title` headings and a 'managed by AUDiaGentic' notice, instead of noisy per-block <!-- AUDIAGENTIC:BEGIN/END --> comments around every entry. Old files migrate automatically on the next surface apply.
- Disabling or uninstalling a component that contributes workflow tags now removes its generated skill/command files from every provider (Claude, Codex, OpenCode, Cline, Gemini), not just the doctrine blocks - and they return on re-enable.
- Added the first reusable component-feature foundation slice and aligned the multilayer plan before moving to the next staged migration.
- Prepared the agent-jobs action migration by proving feature-loaded actions preserve existing tag behavior.
- Moved agent job actions onto the new feature descriptor format without changing prompt or surface behavior.
- Completed the agent-jobs action descriptor cutover to feature-only loading.
- Added the generic implementation and binding foundation needed before migrating coding-lsp.
- Moved coding-lsp languages and the native ag-lsp implementation onto the reusable feature/implementation descriptor pattern without changing runtime behavior.
- Made coding-lsp provider projection implementation-aware so AG LSP can be turned off when another LSP implementation is selected.
- Added explicit ag-lsp-to-language bindings so LSP implementations can declare which language features they support and what each language requires.
- LSP status now shows which implementation is active and how configured languages map to feature state.
- Added LSP management tools for listing and switching active LSP implementations.
- Added the alternate agent-lsp implementation path and projection so coding-lsp can switch between native ag-lsp and external agent-lsp.
- LSP language features now have validated options that persist in feature state and affect runtime language server settings.
- Updated the multilayer component plan to show what has landed and identify the remaining major LSP cutover decision.
- Updated the multilayer component plan with completed stage details and clarified the next LSP decommission action.
- Added the missing LSP switch persistence test and clarified writer-key status in the plan.
- Clarified Stage 2 decommission sequencing so writer-key projection is unblocked before resolver-driven projection work starts.
- Implemented binding writer-key dispatch for generic LSP projection and updated the Stage 2 plan status.
- Added resolver-driven active LSP runtime server config as the next Stage 2 decommission step.
- Moved LSP session discovery and native provider sync onto the feature-state runtime resolver.
- Moved remaining LSP activation/dependency tests off lsp.json and shrank the legacy language registry path.
- Completed writer-key dispatch for both generic MCP and native language-server LSP projections.
- Completed Stage 2 LSP source-of-truth cleanup: active feature state and bindings now drive session/provider projections, with lsp.json kept as generated cache only.
- Added the provider Stage 3 bridge: providers now participate in the reusable implementation layer while existing provider config/output behavior remains compatible.
- Foundation now supports per-provider features, so each AI provider can own and configure its own capabilities independently.
- Planning doc updated to record provider-migration progress and the chosen approach for modeling provider capabilities.
- Each AI provider's capabilities (MCP, language-server support, surface files, skills) are now modelled as independent per-provider features.
- AUDiaGentic can now compute which provider capabilities are active per enabled provider, the basis for unifying provider config projection.
- MCP server config is now written only to enabled providers and cleaned up from disabled ones, avoiding stale config for providers you do not use.
- Provider surface files (CLAUDE.md, AGENTS.md, skills) are now written only for enabled providers and cleaned up when a provider is disabled.
- Language-server config is now synced only to enabled providers (and cleaned from disabled ones), completing enabled-aware projection for all provider capabilities.
- Added reviewed architectural integrity findings to the multilayer component plan with validity and target-stage classification.
- Hardened the feature binding loader so non-LSP bindings cannot silently inherit a language-specific default.
- Provider VS Code extension probe failures now use AUDiaGentic's standard error envelope instead of raw framework-specific strings.
- VS Code extension status is now optional/unknown when unavailable, rather than treated as a framework failure or false negative.
- Feature and provider action descriptor loaders now use AUDiaGentic's standard structured error management instead of raw ValueError validation failures.
- Corrected new structured error codes to match AUDiaGentic naming conventions and documented the error-code audit follow-up.
- Removed unused surface helpers that hardcoded provider alias names.
- Removed dead internal helper functions and verified module boundaries are clean.
- Added architecture review findings and closeout gates for component isolation and config-driven capability management.
- Foundation no longer reaches into the providers component for provider ids; provider-id discovery now lives with the providers.
- Tidied LSP code and instructions by removing a dead constant and correcting docs to reflect feature-state-driven language config.
- Cleaned up LSP config handling so language state, default implementation, discovery, and project-root detection no longer treat the lsp.json cache as a source of truth.
- Moved VS Code host probing out of the provider registry and into a host capability service.
- Decoupled runtime MCP projection from provider internals and removed unused runtime-owned harness provider descriptor.
- Replaced the temporary MCP projection sink registry with lifecycle/event-bus based provider projection.
- Added event migration candidates and non-event architecture cleanup items to the multi-layer component plan.
- Decoupled provider reconcile from runtime MCP sync helpers and moved shared MCP JSON helpers into foundation.
- Moved LSP provider projection to event-driven provider-owned handling and removed provider imports from the LSP sync module.
- Moved provider-aware ID validation out of foundation and into the providers component wrapper.
- Updated the multi-layer component plan with the valid architecture review findings while filtering out overbroad cleanup work.
- Added a concise ordered completion plan for the remaining multi-layer component architecture work.
- Small cleanups fixed inline logger eliminated silent error swallowing reconciled plan items
- Fixed ledger fragment filename sanitization for Windows compatibility
- Docker e2e fixes
- Cleaned stale plan status so the next implementation step is based on current architecture state.
- Each AI provider's config-writing capabilities (MCP and language-server config) are now individually tested via the provider's own adapter, catching mis-wired providers.
- Completed foundation config isolation and small error/schema cleanup items from the architecture plan.
- Lifecycle-unit, release-integration, and release-e2e tests now run in the normal test suite instead of Docker-only, since they were verified not to touch the real environment.
- Moved provider aliases into provider descriptors and removed central provider/harness edit lists.
- Generalized provider host capability metadata while keeping VS Code as the only concrete host probe for now.
- Converted a small public-boundary error slice to structured errors and removed a broad silent swallow in ledger sync.
- Converted additional MCP and LSP public-boundary errors to structured AUDiaGentic errors.
- Lifecycle and provider integration tests now run in the normal test suite (not Docker-only) by redirecting the AUDiaGentic home to a temp dir, with verified zero pollution of the real environment.
- LSP generic MCP projection now comes from implementation descriptors, so new supported LSP implementations no longer require editing the sync module for managed IDs or entry builders.
- Provider and MCP error reporting now avoids leaking raw provider streams or obvious secrets in returned error envelopes.
- Event bus diagnostic logs now include structured fields, making subscriptions and subscriber failures easier to trace in JSON logs.
- CLI and lifecycle e2e tests now run on the host (they only write config, not code); tests that actually install code remain isolated.
- Dependency probes now use simple declarative probe syntax instead of Python module paths in shipped config, without adding a new registry layer.
- Consolidated MCP server construction onto a single foundation factory and shared entry point, removing duplicated bootstrap and import-guard boilerplate across four servers.
- Removed a duplicate surface-file dataclass by reusing the shared component-file type.
- Factored the shared shape of component and surface descriptors into a common base tier, removing duplicated field declarations without conflating the two domains.
- Factored the feature, implementation, and binding descriptors onto a shared base tier, removing duplicated field declarations while keeping each type distinct.
- Baseline sync no longer creates prompt syntax or prompt catalog files for unfinished agent-jobs surfaces; those values are derived from descriptors at runtime with project overrides still supported.
- Baseline sync now only copies declared source files and no longer embeds component-specific rendering logic for virtual assets.
- Fixed stale LSP projection tests that broke after projection facts moved into descriptor metadata.
- Release finalization now uses evented ledger ownership for archive/sync work while keeping the synchronous release API behavior unchanged.
- Framework validation and shared config/path/process helpers now use AUDiaGentic's structured error model instead of raw exceptions or process exits. Plan now records completed A14/A26 slices and remaining classification work.
- Generic harness and rig helpers now report structured AUDiaGentic errors instead of terminating the process. Remaining exit cleanup is limited to CLI/harness-specific flows that need classification.
- LSP language config is now sourced from the shared feature catalog, removing a duplicate config parser.
- A26 complete. Shared library code now reports structured AUDiaGentic errors instead of exiting the process. Remaining exits are intentional CLI boundaries.
- Removed import-time evaluation of LSP language dependencies so the shared feature catalog is the live source at runtime.
- Component CLI no longer duplicates harness refresh logic. Lifecycle mutations now go through the project component API, keeping side effects centralized without adding unnecessary eventing.
- Removed dead provider surface bridge config and code now that provider capabilities come from the provider descriptors.
- Unified CLI output: all CLI and harness print calls now route through cli_io module for consistent stdout/stderr separation and JSON serialization.
- Fixed structured errors so they can carry tracebacks and chain causes; exceptions raised through context managers no longer crash.
- Cleaned up the LSP language catalog so feature descriptors are the source of truth and the LSP registry is only a runtime adapter.
- Cleaned up import-ordering lint errors so the source tree passes Ruff.
- Validated the provider-LSP end-to-end suite in Docker (25 passed); the prior failure was a Windows volume-mount issue, fixed by baking source into the image.
- Made all Docker test images use a consistent source-baking approach so they run on Windows, and fixed two images that could not build.
- Disabling the LSP component now fully removes its language-server config from every provider, leaving no empty 'lsp' block behind.
- Decoupled CLI layer from optional components using service registry. Fixed error handling in schema/ID validators.
- Enabling the LSP component no longer hangs/times out — the pi-lens extension install now runs in the background instead of blocking the request.
- Fix LSP management MCP instructions to include lsp_list_languages and lsp_list_missing
- Fix: removing an LSP language now properly cleans up provider config entries
- Add regression test: removing an LSP language must prune provider configs
- Fixed remaining architecture warnings: error handling, silent exceptions, missing loggers.
- Enhance code-cleanup.md with detailed remediation plan for remaining architecture violations
- Fix remaining architecture violations: raw ValueError -> AudiaGenticError, silent except:pass, missing loggers
- Scoped all outstanding plan items with concrete implementation plans.
- Split cleanup plan into active and completed docs; added 5 unswept standards
- Validation pass 4: added 5 Std 8 sites, corrected Std 9 count 13->10, clarified redaction scope
- Completed 6 cleanup items: error redaction, cli_registry revert, 7 except Exception fixes, ID constants deprecation, 10 extra={} logs, SystemExit fix
- Hardened LSP transport layer: notification dispatch, server request handling, method-specific timeouts, crash recovery, expanded client capabilities, and file-level diagnostics with publishDiagnostics cache.
- Code cleanup pass 4: 7 items completed. Error detail redaction, 7 except Exception fixes, 10 entity log extras, cli_registry revert, SystemExit narrowing, packet_runner logging, LanguageServerEntry moved out of foundation.
- Completed LSP MCP enhancement plan: capability discovery, normalized schemas, 18 documented MCP tools, navigation expansion (typeDef, impl, callHierarchy, symbolContext), code actions/format preview, provider routing policy, post-edit feedback loop. Fixed hardcoded paths in config.
- Refactored the foundation layer to support a more modular component architecture.
- Restructured planning documents: each plan now has an index file linking to individual item files for better traceability and state tracking
- Restored full execution detail to plan items — each item now includes line anchors, budgets, and acceptance criteria
- Split remaining docs root plans into actionable items; moved completed plans to completed/ directory
- Verified plan content coverage, added missing deferred/rejected items, removed redundant originals
- Clean up stale tests: removed dead smoke tool test, updated component registry test after planning component removal
- Fix options provenance bug and clean up 7 stale tests across registry, LSP, contracts, lifecycle, and tools
- Fixed LSP diagnostics on Windows: single-file diagnostics no longer return empty due to drive-letter/URI casing mismatches, and workspace diagnostics fail fast with clear guidance instead of hanging 30s on servers (like pyright) that don't support workspace pull diagnostics.
- Fix e2e test subprocess PYTHONPATH and update stale assertions for prompts lifecycle change
- Workspace diagnostics now work with pyright: lsp_diagnostics falls back to a pyright --outputjson project scan when the language server doesn't support LSP workspace pull, instead of hanging. Capability reporting fixed so lsp_capabilities lists the methods a server actually supports.
- Wired up dependency version checking, harness instruction derivation, and contribution config reference validation — all previously implemented but not connected.
- Code cleanup: removed duplicated logic, dead branches, and verbose patterns across 7 files.
- Flattened feature state to composite keys, eliminating error-prone 3-level nesting with automatic backward-compatible migration.
- Reconciled plan items: ML05 verified done via dead code audit, ML06 unblocked. Cross-plan duplicates (CC07/ML01, CC09/ML03) documented.
- Code simplification pass: reduced code size and complexity across 10 files by eliminating repetitive patterns, removing dead code, and extracting shared helpers.
- Verified CC09/ML03 VS Code extensions.json implementation complete. Fixed missing _ensure_dict utility that blocked provider adapter imports.
- ML06: Resolved stale open questions in LSP plan docs, fixed lsp.json documentation, verified Docker e2e test readiness.
- Enable multiple LSP servers per language (e.g., pyright + ruff for Python). Sessions keyed by (language, server_id). Navigation tools route to first capable server; diagnostics merge all servers.
- Replace if/elif command dispatch with registry tables in launcher.py for cleaner extensibility.
- Expanded LSP capability surface: pull diagnostics (CAP02), ruff as second Python server (CAP03), read-only tools for inlay hints/signature help/type hierarchy/completion (CAP04), mutation gating via opt-in config (CAP05), capability matrix coverage (CAP06), install recipe validation (CAP07).
- Centralize path constants and fsync patterns across state layer for maintainability.
- Added Docker e2e integration tests that install all language servers and validate every MCP tool against real source code for Python, TypeScript, Rust, and C++. Covers multi-server diagnostics merge (pyright + ruff).
- Centralize ledger path constants in component configuration for maintainability.
- Replace if/elif command dispatch with registry tables in component CLI.
- Extract hardcoded LSP constants (timeouts, kind maps, severity, markers) to centralized lsp_constants.py.
- Extract URI/path utilities from LspSession into uri_utils.py.
- New planning component for managing plan items across sessions. MCP tools let agents create, list, read, update, transition, and delete plan items in docs/planning/plans/. Items move from active/ (pending) to completed/ as work finishes. Structured as component + local-docs implementation so alternative backends (Jira, Linear) can be added later.
- Added planning component management MCP (ag-planning-mgmt) so agents and the CLI can list available planning implementations and switch between them without editing config files. Follows the same pattern as the LSP management server.
- Folder names for plan items are now configured in the implementation descriptor YAML (local-docs.yaml paths: block) and read at runtime via the features registry. No hardcoded paths remain in the Python code — switching implementations automatically uses the new implementation's configured paths.
- 49 unit and integration tests added and passing for the planning component. Tests cover all six MCP operations, validation errors, state transitions, the not_done legacy alias, and the full create-update-complete lifecycle.
- Fixed 3 failing MCP project server e2e tests related to project_root fixture usage
- Planning component now correctly propagates ag-planning to all provider MCP configs (Claude, Codex, Gemini, Goose, OpenCode, Continue) and injects the planning process contribution into CLAUDE.md on install. 21 new tests across integration and e2e tiers verify both lifecycle propagation and end-to-end MCP server behavior. Two Docker-gated tests verify harness config after install.
- Planning harness MCP tests now run without Docker. Five tests verify that after installing agent-planning, both ag-planning-mgmt and ag-planning appear in the harness mcp.json collection (via collect_mcp_servers and build_pi_mcp_dict), and that neither appears when the component is uninstalled or disabled.
- CC11 progress: Extract hardcoded LSP constants and URI utilities, reducing 3 god object files.
- CC12: Consolidated rig error factories and platform constants
- CC11: Extract hardcoded LSP constants and URI utilities from 3 god objects into centralized modules.
- CC15: Replace session if/elif scope dispatch with registry tables and use make_error() consistently.
- CC16: Consolidate release-please template rendering and workflow sources.
- CC17: Consolidate update module constants and platform-specific code.
- CC18: Fix source_control dual-component lifecycle handler and copy-paste.
- CC19: Consolidate foundation duplication — pid_alive dedup, probe/descriptor/platform/formatter registries.
- CC19: Decompose StatePropagationEngine god object into focused classes.
- CC11: Decompose LSP god objects — LspSession split into focused classes.
- Runtime feature state is now stored as one file per component instead of a single shared file, so enabling or configuring one component no longer rewrites every other component's saved settings. Existing single-file state is migrated automatically and the old file is preserved as a .migrated backup.
- Fixed MCP e2e test hang with parallel xdist execution and improved rust-analyzer readiness checks
- Fixed rust-analyzer initialization and indexing in e2e LSP tests: 59 pass, 4 skip
- Added diagnostics and code_actions tests that verify LSP detects real code errors
- Fixed all rust-analyzer e2e LSP tests: 68 pass, 0 fail (was 59 pass, 4 skip, 58 pass, 1 skip)
- Foundation, runtime, ledger, session, planning and release-please infrastructure
- Fixed all 68 Rust-analyzer e2e LSP tests
- Planning docs migration, e2e test harness, agent config alignment
- Component markers are now auto-derived from the component id. The loader defaults detection-marker to .audiagentic/components/<id>.yaml (project scope) or components/<id>.yaml (harness scope) and synthesizes the marker ComponentFile when not explicitly declared. All 9 component descriptors had their redundant marker blocks removed. Docs and tests updated.
- Removed dead duplicate core/project/ and core/session/ directories from components/. These were unreachable leftovers from a refactor — the live components are in components/project/ and components/session/.
- The 'What you can do' tool catalog in harness instructions is now auto-generated from MCP server declarations (direct-tools + tool-descriptions). Hand-written tool lists removed from all 9 component descriptors. Only free-form operating rules and doctrine remain in harness-instructions (kept in separate named sections). Providers.yaml converted from direct-tools: true to explicit list. Templates updated to reference 'MCP tools' section.
- Added regression tests for markdown LSP support
- Split logging formatter/handler classes into dedicated formatters.py module for better separation of concerns.

## rel_0003
- Fixed GitHub authentication for release dispatch: device-flow OAuth now works as a non-blocking start/poll pair over MCP, with GITHUB_TOKEN environment-variable support as an immediate alternative.
- LSP tools now auto-install missing language servers from their YAML recipes when a file is opened
- Added Agent Profiles component: manage provider+model bindings per-project, resolve profiles at job launch, with MCP tools for CRUD and resolution. Agent jobs now support agent-profile-id directive with automatic provider enablement checks.
- Fixed stale MCP and language-server processes piling up after the agent host exits or is killed — child processes are now reliably terminated with their parent on all platforms.
- MCP servers now launch without flashing console windows and with fewer background processes each, and every provider config — even ones you're not currently using — is kept in sync.
- Tests now run from one command (`make test-all` / `tests/run_all.py`): the full non-Docker suite executes in parallel, and Docker suites run automatically when a daemon is present. Docker images were consolidated where safe (faster, parallel CI), while the recipe install/uninstall tests stay isolated so they keep genuinely testing dependency installation.
- Running `python tests/run_all.py` on Windows now delegates everything to Docker when a daemon is present - no duplicate test passes. If no Docker daemon, falls back to the Windows-safe non-mutating suite.
- Unified the test suite so a single command (`python tests/run_all.py`) runs everything — when Docker is present it handles all phases; without Docker it runs the parallel host suite. Fixed 9 failures found by the first full consolidated run, covering provider descriptor metadata, LSP config key naming, Docker assertion format, and two Docker image build failures.
- Fixed ag-lsp workspace diagnostics on Windows by launching batch diagnostic CLIs through a Windows-safe wrapper, preventing WinError 2.
- Made ag-lsp skip broken or missing language servers instead of failing the whole request.
- Expanded test coverage so every declared Python MCP server is smoke-tested automatically, and added a small host-side smoke phase to catch local Windows PATH/CLI breakage that Docker cannot see.
- Fixed the broken coding-lsp status hook and hardened CLI probe decoding so MCP smoke no longer throws Unicode decode crashes.
- Added JSON, TOML, and Makefile language support to coding-lsp, including proper Makefile basename matching and unit coverage.
- Docker test infrastructure now includes Go toolchain and validates make-ls auto-install in a blank container environment.
- Makefile LSP dependency now uses the structured go toolchain pattern instead of platform-specific fallback commands.
- Added memory component — persistent memory for agent sessions with swappable backends. Hindsight is the default implementation. Memory config projects into provider surfaces with per-provider integration modes.
- Fixed memory component architecture — removed provider-specific logic. Memory now contributes generic content through the existing surface contribution system; providers handle rendering.
- Added a reusable provisioning-recipe foundation so provider integrations (memory/Hindsight, LSP) can install, configure, verify, and cleanly uninstall host tooling through shared, safe primitives.
- Memory (Hindsight) and LSP now have full install/verify/uninstall recipes on the shared provisioning model, plus a verified harness integration matrix mapping each supported tool to its install strategy.
- Added PRR06 (LSP recipe adapter) and PRR07 (architecture regression tests) to complete the provider-recipe-refactor plan. The LSP adapter documents how coding-lsp fields map to recipe concepts without changing behavior. 14 regression tests verify ownership boundaries are maintained.
- Refactored recipe architecture: foundation toolchains are now provider-agnostic, provider-owned capability recipes manage harness integrations, and memory component no longer orchestrates provider refresh.
- Refactored recipe architecture: foundation toolchains now provider-agnostic, provider-owned capability recipes manage harness integrations, memory component no longer orchestrates provider refresh.
- Updated Hindsight memory plans to prevent provider-specific memory code, guessed installer commands, and toolchain/provider boundary leaks.
- Tightened memory/provider compartmentalization: memory no longer owns Hindsight MCP config or provider surface text, and unverified Hindsight installer commands are blocked rather than executed.
- Contained Hindsight-specific provider setup under the memory Hindsight implementation instead of embedding it in the providers component, with tests guarding the boundary.
- Hindsight integration commands now substitute backend config values for placeholders
- Provider recipe refactor completion: recipes now owned by provider surfaces, config migrated to YAML model, architecture boundary tests added
- Memory hindsight migration: provider-owned backend with per-provider strategy matrix, export contract, and regression tests
- Provider descriptor YAML planning scaffold with architecture docs updates
- Reviewed PDxx and HMxx for containment, updated the plans to keep Hindsight-specific logic inside the memory Hindsight implementation, and removed a legacy backend accessor plus unsafe shell-command execution behavior.
- Memory hindsight cleanup: removed deprecated recipe, finalized provider migration
- Updated PD/HM plans so executing agents know the safe implementation order, which tasks need review, and the containment pitfalls to avoid.
- Platform key consolidation and hindsight integration matrix — added canonical platform detection function, consolidated platform references across 6+ modules, and created source-backed integration matrix for 17 provider-harness combinations with platform-aware command parameterization.
- Fixed Hindsight containment gaps from the review: rule blocks now install from memory/hindsight, orchestration entrypoints exist, OpenHands no longer falsely reports automated support, and plans now clearly forbid provider-owned Hindsight implementation.
