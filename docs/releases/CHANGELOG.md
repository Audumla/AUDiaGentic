# Changelog

## [0.4.0](https://github.com/Audumla/AUDiaGentic/compare/v0.3.1...v0.4.0) (2026-10-24)


### Features

* **gateway:** rotate daily journals with protected five-day trace retention ([83e3dd5](https://github.com/Audumla/AUDiaGentic/commit/83e3dd5393df4c3b413c3f5d267d3aa914792615))


### Bug Fixes

* **ci:** align gateway boundaries and integration contracts ([81e8ca4](https://github.com/Audumla/AUDiaGentic/commit/81e8ca426be16db5c4f82ea746d1ef9004b50af4))
* **ci:** repair contract checks and clean-room test inputs ([abd84de](https://github.com/Audumla/AUDiaGentic/commit/abd84de34b483bf4bcbfab1e9e58690f403a7377))
* **ci:** repair contract validation and clean-room test baselines ([39a3080](https://github.com/Audumla/AUDiaGentic/commit/39a3080621277ede9f7f6c1c4f9fdbe995516298))
* **ci:** use declared test dependencies and time-bound ACP responses ([dce4c07](https://github.com/Audumla/AUDiaGentic/commit/dce4c072ec8fb2913854c822a9d5eb73217f2b86))
* **gateway:** avoid repeated quadratic journal compaction ([38ff048](https://github.com/Audumla/AUDiaGentic/commit/38ff048a57fc305ad3841bf7f86bdc8164b827d4))
* **gateway:** capture activity boundary before provider execution ([c2664ab](https://github.com/Audumla/AUDiaGentic/commit/c2664ab10ba44f0a4fc1c3bcf3c5f1ab1e9c320d))
* **gateway:** preserve progress before watcher thread starts ([7a8b831](https://github.com/Audumla/AUDiaGentic/commit/7a8b831f52c3357750f1774407d63789f1b8b782))


### Documentation

* **ci:** synchronize repair ledger and validation status ([3d7f8a2](https://github.com/Audumla/AUDiaGentic/commit/3d7f8a2cd5e1041a9da9a41f6d9ba2b632bf1d28))
* **planning:** disambiguate pull request references from plan IDs ([9dc6882](https://github.com/Audumla/AUDiaGentic/commit/9dc6882893fe37f9a9dd5fca13f517cc7a5e056c))

## [0.3.1](https://github.com/Audumla/AUDiaGentic/compare/v0.3.0...v0.3.1) (2026-10-23)


### Bug Fixes

* **gateway:** recover completed turns and trace request startup ([872fef2](https://github.com/Audumla/AUDiaGentic/commit/872fef2f296958d58e24b17a2893a595e965058b))
* **release:** reconcile legacy ledger before publish ([2d0dd6c](https://github.com/Audumla/AUDiaGentic/commit/2d0dd6c671c87e4733016bff243beb7c3e7485b5))

## [0.3.0](https://github.com/Audumla/AUDiaGentic/compare/v0.2.1...v0.3.0) (2026-10-20)


### Features

* add operator GPT response capture ([1687eb6](https://github.com/Audumla/AUDiaGentic/commit/1687eb6f17e339400f39de7688b256f633426068))
* externalize local runtime settings ([a9fed7a](https://github.com/Audumla/AUDiaGentic/commit/a9fed7a1f2e2e41e758f20a96a26525b4c8584fa))
* **gateway:** add request observability and compact MCP evidence ([9cf1c9f](https://github.com/Audumla/AUDiaGentic/commit/9cf1c9f47bb7e4dff4450ff18d9da4bf878fc3ad))
* **gateway:** bound observability retention ([a5b6131](https://github.com/Audumla/AUDiaGentic/commit/a5b6131bb0bbcd0f78b10b2049abc3e5118a99af))
* **ledger:** make release notes ledger-backed and archival-safe ([0c79cbc](https://github.com/Audumla/AUDiaGentic/commit/0c79cbcc10f3f2a71001049025815e8917d876eb))
* **release:** make templates language neutral ([4b6c29c](https://github.com/Audumla/AUDiaGentic/commit/4b6c29cb44d67cd380ceb32283878875aca3f34b))


### Bug Fixes

* accept ChatGPT rich-link composer rendering ([d69d79e](https://github.com/Audumla/AUDiaGentic/commit/d69d79ea0c191216928890bad1156205370b30a5))
* accept governed prompts during provider capture ([64cce0a](https://github.com/Audumla/AUDiaGentic/commit/64cce0a4032071ad619678672165834be63067df))
* activate new project target before navigation ([87cb0fb](https://github.com/Audumla/AUDiaGentic/commit/87cb0fb3037b0f113bad7c558541b09012c9c505))
* activate project tab before cdp chat click ([f831b79](https://github.com/Audumla/AUDiaGentic/commit/f831b791db98b7c56dd09b5b30891ebfaedd623d))
* avoid full dom scan during composer readiness ([b0f0134](https://github.com/Audumla/AUDiaGentic/commit/b0f013451d07d9760297158fff1358cdeaba129b))
* bound dashboard anchor tab creation ([83803af](https://github.com/Audumla/AUDiaGentic/commit/83803af666edaa3ed28875fd65657e144a3d686c))
* bound gpt-auto cancellation settlement ([6e4f45c](https://github.com/Audumla/AUDiaGentic/commit/6e4f45c5f448a1a1a1e5259f3d5e81e10f5648e0))
* bound gpt-auto CDP observations ([a96f05e](https://github.com/Audumla/AUDiaGentic/commit/a96f05e7f62490ae8fa51f44037cf6935e0266dc))
* bound provider reconciliation snapshots ([73c5c71](https://github.com/Audumla/AUDiaGentic/commit/73c5c7151f25e14635bb6f6cd386a5de924d355b))
* bound stale provider-session recovery ([6ad7ca8](https://github.com/Audumla/AUDiaGentic/commit/6ad7ca85c04c70b7effc53f2ca7d597de9c27d1b))
* close carrier-ownership and label-ownership gaps in gpt-auto fallback ids ([3517b3b](https://github.com/Audumla/AUDiaGentic/commit/3517b3b711d59db14f74f64db6b4727f7a6e9c78))
* close GPT-auto lifecycle audit findings ([908c92c](https://github.com/Audumla/AUDiaGentic/commit/908c92c1c64b236d34721b5c4ed09ef28dbf295f))
* close remaining gpt-auto lifecycle gaps ([da8ac39](https://github.com/Audumla/AUDiaGentic/commit/da8ac393d8dd3f0e2044b37f88061f633fc54fdc))
* close review findings on gpt-auto fallback message-id extraction ([79ccef8](https://github.com/Audumla/AUDiaGentic/commit/79ccef8572779514c83bd6c7c80412be71e403cb))
* correlate GPT fallback activity and defer queued turn timeouts ([e74d82a](https://github.com/Audumla/AUDiaGentic/commit/e74d82aff548cf56837e57d5c4cd4b2d94891bf5))
* correlate GPT-auto provider alerts to requests ([2e98dad](https://github.com/Audumla/AUDiaGentic/commit/2e98dad3a5ce1db51cb65d89c01d9386013280f8))
* count GPT-auto DOM edge activity ([364b4f9](https://github.com/Audumla/AUDiaGentic/commit/364b4f9c9593489ae37dd99a2004d7e08e2fedf2))
* detect and click the current plain-text delivery-timeout Retry control ([1285bc3](https://github.com/Audumla/AUDiaGentic/commit/1285bc3323fd2a443fcc67c424c5e03fd32b1f5a))
* emit gpt-auto activity before readiness ([503fa04](https://github.com/Audumla/AUDiaGentic/commit/503fa049b2ffce0ed616f507dfb6f1a5dee82286))
* fence orphan watchdog terminalization ([93531ac](https://github.com/Audumla/AUDiaGentic/commit/93531ac0c27624692fe8af18166fc845e68e42ec))
* fence provider capture recovery ([20af0cb](https://github.com/Audumla/AUDiaGentic/commit/20af0cbe37e3016688175122ead30fd0f0238a14))
* fence reusable-session submission proof ([0a644ef](https://github.com/Audumla/AUDiaGentic/commit/0a644ef640dffb8f4e330ffbc22010e3741af9ac))
* fence unresolved provider capture ([3dceb0b](https://github.com/Audumla/AUDiaGentic/commit/3dceb0b31fb8bb8c251abc90e3870f092f22601b))
* finalize cancelled gateway recovery workers ([2a5ad66](https://github.com/Audumla/AUDiaGentic/commit/2a5ad66308d11fb79a7d872b2d2fb067840278d7))
* **gateway:** avoid reusing terminal GPT sessions ([605bdf2](https://github.com/Audumla/AUDiaGentic/commit/605bdf2e3735e5167468eba70a3f93458e57e58d))
* **gateway:** bound evidence and request reads ([3ea4e70](https://github.com/Audumla/AUDiaGentic/commit/3ea4e7022a3b819a7b06bb84f45dc6defbc6c29d))
* **gateway:** bound presubmit reconciliation waits ([334b300](https://github.com/Audumla/AUDiaGentic/commit/334b30034d6f39eb18ea65a70fa671b24d77dc22))
* **gateway:** close follow-up audit findings ([9594b2f](https://github.com/Audumla/AUDiaGentic/commit/9594b2f88c61fdbfa389fb85c567d059261ca9cc))
* **gateway:** close observability and recovery review gaps ([67105cf](https://github.com/Audumla/AUDiaGentic/commit/67105cf7c1f08fd108a5f4f3fa0d0b2291eb93b4))
* **gateway:** close post-fix observability audit ([3ffd558](https://github.com/Audumla/AUDiaGentic/commit/3ffd5580fb8dba9e2810c6317e15cec2f5a5091e))
* **gateway:** close recovery race findings ([4b27967](https://github.com/Audumla/AUDiaGentic/commit/4b279672fa7138b747e74df26ef5197a81ed11af))
* **gateway:** complete GA03-GA05 observability audit ([cd3ecbe](https://github.com/Audumla/AUDiaGentic/commit/cd3ecbed8ce632b7e5702111d7087c7d146b1127))
* **gateway:** correct observation MCP signature ([23d260e](https://github.com/Audumla/AUDiaGentic/commit/23d260e0897bc2ac511cea10b5bdffd79166f4cf))
* **gateway:** fence native recovery actions ([4e5f5d5](https://github.com/Audumla/AUDiaGentic/commit/4e5f5d5e119163f37aa13504be9465649aea54a6))
* **gateway:** fence recovery session finalization ([3b37d24](https://github.com/Audumla/AUDiaGentic/commit/3b37d24e029281ce14458f0fc956f048a7dbc95d))
* **gateway:** harden observability evidence boundaries ([719721c](https://github.com/Audumla/AUDiaGentic/commit/719721cdc921f65fcd2649e8ba024836bcfd5f5d))
* **gateway:** harden recovery and completion tracking ([6020163](https://github.com/Audumla/AUDiaGentic/commit/6020163a28db99380b429a9c067ca08c9f3f6143))
* **gateway:** harden recovery and terminal reconciliation ([8b8c6d6](https://github.com/Audumla/AUDiaGentic/commit/8b8c6d677dfd57a3fca9677c601a8cfa963d4821))
* **gateway:** reconcile adoptable failures during status ([e644ffb](https://github.com/Audumla/AUDiaGentic/commit/e644ffb2e679ac742dc5138fd4dd7c5c3d2b6b9b))
* **gateway:** reconcile transient GPT completion races ([11cd1f7](https://github.com/Audumla/AUDiaGentic/commit/11cd1f75f435f495d00ef22c292a1fedbd159be4))
* **gateway:** replay interrupted session finalization ([cba8969](https://github.com/Audumla/AUDiaGentic/commit/cba8969c917c57998c65b63fa01892e087ed7a70))
* **gateway:** retry unstarted new sessions ([2abec09](https://github.com/Audumla/AUDiaGentic/commit/2abec09b431d1b8fd38bcdcfb2da1f30485ae894))
* **gateway:** seek indexed deep cursors ([7b54b02](https://github.com/Audumla/AUDiaGentic/commit/7b54b0258b3cfeded2fcfc85d77388e02e512eb0))
* **gateway:** serialize GPT session recovery ([a9aeec2](https://github.com/Audumla/AUDiaGentic/commit/a9aeec255dbc8f486ca673c696e6da3a95b63188))
* give a failed delivery-timeout retry probe one more poll before failing ([8ce3e8d](https://github.com/Audumla/AUDiaGentic/commit/8ce3e8dd90f8590211f39f44cf267c43b62bad3a))
* **gpt-auto:** accept assistant DOM identity replacement ([b2b86e3](https://github.com/Audumla/AUDiaGentic/commit/b2b86e3d8587a427d5a033ab026dc53a2df56542))
* **gpt-auto:** admit completed project-root turns ([b302700](https://github.com/Audumla/AUDiaGentic/commit/b302700118d434944fa3a47a14bdd4e760e3f6b7))
* **gpt-auto:** adopt openerless project tabs ([8110dca](https://github.com/Audumla/AUDiaGentic/commit/8110dca964b8f79a520b9325691d6b7d7d90d608))
* **gpt-auto:** bound lost send acknowledgements ([5c8459e](https://github.com/Audumla/AUDiaGentic/commit/5c8459e1b996b1e7b51e601b3e7cbe46075acead))
* **gpt-auto:** harden response identity recovery ([754016c](https://github.com/Audumla/AUDiaGentic/commit/754016c794fabfc264e7685bfbb444d46cd0476c))
* **gpt-auto:** hover project action before click ([04c71a9](https://github.com/Audumla/AUDiaGentic/commit/04c71a9bde2b3e83144aa3cc2742957afee362a6))
* **gpt-auto:** keep proven replacement in normal recovery flow ([c8d3f4d](https://github.com/Audumla/AUDiaGentic/commit/c8d3f4d7a494ac276aabc3ba59d282a806f8bc3e))
* **gpt-auto:** pin first fresh session response ([426f81c](https://github.com/Audumla/AUDiaGentic/commit/426f81c7b68e6931d8bff361ae09b49f05cdebd8))
* **gpt-auto:** preserve completion over stale remount errors ([d17d080](https://github.com/Audumla/AUDiaGentic/commit/d17d080297ff692feb65573ffda16df0fea2af00))
* **gpt-auto:** preserve terminal assistant remounts ([f473894](https://github.com/Audumla/AUDiaGentic/commit/f473894e25fee4ff7bc0e410d81cbe492834a329))
* **gpt-auto:** reconcile reversed DOM turns ([324968e](https://github.com/Audumla/AUDiaGentic/commit/324968e175d2a037c57441f78ba5f4d201d363b0))
* **gpt-auto:** recover terminal assistant remounts ([26a1fe0](https://github.com/Audumla/AUDiaGentic/commit/26a1fe025c5d0e9694b7781026a17447c9690e55))
* **gpt-auto:** support configured remote CDP endpoints ([560ed72](https://github.com/Audumla/AUDiaGentic/commit/560ed722f921d2f26a31f3e926565c048f59c4d2))
* **gpt-auto:** trust decisive completed turns ([18fcbb0](https://github.com/Audumla/AUDiaGentic/commit/18fcbb0388b68c8beeae22a863f918b4caf3b305))
* **gpt-auto:** use remote CDP endpoint ([2089ed9](https://github.com/Audumla/AUDiaGentic/commit/2089ed93b0078c00bc112d54270df46b6aff2cb8))
* **gpt-auto:** use trusted project controls ([ab01418](https://github.com/Audumla/AUDiaGentic/commit/ab01418bb9375c956c8ed3de23af4b78c3300e7d))
* harden gateway FIFO cancellation and GPT activity leases ([4852f5c](https://github.com/Audumla/AUDiaGentic/commit/4852f5cd6300e1eff5aa6e9efc2cc294450f1b78))
* harden release ledger archival boundaries ([ae380be](https://github.com/Audumla/AUDiaGentic/commit/ae380beb6b4f2cb3a51b46419af83cc6aeda6f94))
* ignore collapsed GPT prompt markers ([eb64c6a](https://github.com/Audumla/AUDiaGentic/commit/eb64c6a16e9672e5a74e070e43050619af0a22cb))
* ignore failed delivery retry probes as activity ([3138636](https://github.com/Audumla/AUDiaGentic/commit/3138636f09e31e8a07faab11e892ed93e6391d08))
* isolate FIFO request checkpoint relays ([e6060fa](https://github.com/Audumla/AUDiaGentic/commit/e6060fa05648f5efa837195ca29c62039672aec6))
* keep active GPT response observation lease alive ([542920b](https://github.com/Audumla/AUDiaGentic/commit/542920ba0d1a6aca88fc5bd18b528f13077147e8))
* keep long GPT requests visibly active ([25175ef](https://github.com/Audumla/AUDiaGentic/commit/25175ef58ae5d9a1b92814d91b4a21347db7165e))
* **ledger:** make release retries snapshot-safe ([cc2811d](https://github.com/Audumla/AUDiaGentic/commit/cc2811d3b80501a182a61370c6c2df78d7a4d766))
* **mcp:** route requests by durable project ownership ([f303474](https://github.com/Audumla/AUDiaGentic/commit/f3034744b4860184c4f0c49f0c02579d19d7b63c))
* observe meaningful dom class activity ([3af36b2](https://github.com/Audumla/AUDiaGentic/commit/3af36b2480da119a105b7be4d16877656f60a305))
* open GPT project chats through Projects UI ([0c7527a](https://github.com/Audumla/AUDiaGentic/commit/0c7527a0bcb173818d146fe1f4edcd6606001271))
* persist fallback submission proof ([010c41b](https://github.com/Audumla/AUDiaGentic/commit/010c41b016c9621e43e3d4aca754cf187e34c3bb))
* preserve cancellation through recovery ([d4f7c7b](https://github.com/Audumla/AUDiaGentic/commit/d4f7c7b138163efac74ed51ee82719fe9f43b509))
* preserve durable session checkpoints ([ff16ce4](https://github.com/Audumla/AUDiaGentic/commit/ff16ce4ac12582be2979486378481492aa2f376b))
* preserve GPT-auto prompt correlation structure ([89d7ce2](https://github.com/Audumla/AUDiaGentic/commit/89d7ce2c456382a02ea7a83e98704835cd33bf0c))
* preserve provider startup exception details ([9fe57c9](https://github.com/Audumla/AUDiaGentic/commit/9fe57c9e8ba596e458d367d4ea175f868c5e58c8))
* prevent synthetic gateway activity from masking stalls ([cd57f1d](https://github.com/Audumla/AUDiaGentic/commit/cd57f1d6eba621ca34ad2f1eebfe796e8399651e))
* protect queued sessions from idle tab reaping ([e92172b](https://github.com/Audumla/AUDiaGentic/commit/e92172bc5d77b4ce65a24f3becbc86048e7285d2))
* reap GPT tabs by session inactivity ([92dc4c6](https://github.com/Audumla/AUDiaGentic/commit/92dc4c66a67e3ded36342f887a93742e5abb4dff))
* recognize early gpt-auto activity phases ([7ea794c](https://github.com/Audumla/AUDiaGentic/commit/7ea794cd96b46e86fbceb92079d7f755e84e2de1))
* recover missing first-render GPT prompt DOM ([9d9d630](https://github.com/Audumla/AUDiaGentic/commit/9d9d6307628e54548686fdb309a9f3a90946f6c1))
* recover real ChatGPT message ids in gpt-auto fallback renderer ([64f652b](https://github.com/Audumla/AUDiaGentic/commit/64f652bac71770944c2b0a7ae56a9981c0dc68d0))
* recover unresolved provider turns manually ([5a82db5](https://github.com/Audumla/AUDiaGentic/commit/5a82db5e18776bb1100360a7e55e076c5a11d61a))
* relay GPT submission DOM activity ([7ac188e](https://github.com/Audumla/AUDiaGentic/commit/7ac188e3b588d5cb86bbc5fca616b1a540bfd3d1))
* relay submission proof for resumed turns ([485897f](https://github.com/Audumla/AUDiaGentic/commit/485897f13030c84716ab24ceb3c9265743c3787c))
* **release:** publish ledger-generated release notes ([6836319](https://github.com/Audumla/AUDiaGentic/commit/68363196e9ce12cfd1bde56771dbef9f0336880f))
* renew activity for unlabeled GPT fallback turns ([fda58a0](https://github.com/Audumla/AUDiaGentic/commit/fda58a004d36cdcffa03eea8ad60db51131dc192))
* require request-owned provider submission proof ([7508fc2](https://github.com/Audumla/AUDiaGentic/commit/7508fc2c9c346731beb40fbae1b44123598136d2))
* restore GPT conversation lifecycle and durable tab cleanup ([993635d](https://github.com/Audumla/AUDiaGentic/commit/993635dec07d44df633f0a2b46181b4790137c3e))
* resume watchdog reconciliation after operator intent ([b385850](https://github.com/Audumla/AUDiaGentic/commit/b38585071b62ec23d498acd5158bb89eac2a42af))
* route binding proof through active request ([4371471](https://github.com/Audumla/AUDiaGentic/commit/4371471f443df934744538601197a8258b0ba41f))
* scope delivery-timeout-alert detection to the known alert text ([38e430b](https://github.com/Audumla/AUDiaGentic/commit/38e430bdbcb5180d3126041b27a86a77ec349170))
* separate structured request metadata from binding metadata ([96bdbd4](https://github.com/Audumla/AUDiaGentic/commit/96bdbd4dac5ee1e6d5cb343677c5e9ccf96ec02a))
* use native CDP input for GPT project chats ([4a606c7](https://github.com/Audumla/AUDiaGentic/commit/4a606c72f078132fa37e9ed03bb5ae14788538c0))
* use trusted CDP click for project chat creation ([56b6a02](https://github.com/Audumla/AUDiaGentic/commit/56b6a02d7ac87e9b87746a784e7e30a05a4fb382))


### Documentation

* **gpt-auto:** clarify request-owned response identity ([94c8ac0](https://github.com/Audumla/AUDiaGentic/commit/94c8ac0aff566512a3342f0d2ffdb1fdb2b5143e))
* **gpt-auto:** close GP50 response identity fix ([22f9409](https://github.com/Audumla/AUDiaGentic/commit/22f940913e9e4edb871ab88e9f2f2bd786958aec))
* **ledger:** record terminal remount fix ([d809d77](https://github.com/Audumla/AUDiaGentic/commit/d809d77dcf598922afbfa7957dededf276e69b4a))
* link FIFO cancellation review to AS133 ([254939f](https://github.com/Audumla/AUDiaGentic/commit/254939f6e4eca50c17953d0c248a782d9929fa63))
* **planning:** close decisive completion review ([90081f9](https://github.com/Audumla/AUDiaGentic/commit/90081f96d9cd9ac8b01696a601e988f7e436025a))
* **release:** refresh bounded-read audit ([9e1cb13](https://github.com/Audumla/AUDiaGentic/commit/9e1cb1327ca5d49df566c4a0f66d4d009f496b84))
* **release:** refresh deep-cursor audit ([0427633](https://github.com/Audumla/AUDiaGentic/commit/04276332254988a2954c2c93381239f8f89aa77a))
* **release:** refresh gateway audit artifacts ([304caa7](https://github.com/Audumla/AUDiaGentic/commit/304caa7b13805d3ab834c14351744bbe665cd60c))
* streamline MCP tool guidance ([c06d5ab](https://github.com/Audumla/AUDiaGentic/commit/c06d5ab70b0d88913695907a021dea8b201a10d2))
* track gateway regression validation and remaining review gates ([2365bf4](https://github.com/Audumla/AUDiaGentic/commit/2365bf4b0cd7b2d41fe206f3b430cb97aaeb6ab9))

## [0.2.1](https://github.com/Audumla/AUDiaGentic/compare/v0.2.0...v0.2.1) (2026-09-13)


### Bug Fixes

* **release:** install dependencies before finalization ([fc150f3](https://github.com/Audumla/AUDiaGentic/commit/fc150f34a4b490fccff1217dfbca9ad0b9d01250))
* **release:** repair legacy ledger entry ([d571271](https://github.com/Audumla/AUDiaGentic/commit/d57127131f322aefad44a3d73189c6092f79e475))
* **source-control:** disable commit ledger stamping ([85c5ede](https://github.com/Audumla/AUDiaGentic/commit/85c5ede3b26d9c1c31a51a5c0898fbb16e75d712))

## [0.2.0](https://github.com/Audumla/AUDiaGentic/compare/v0.1.1...v0.2.0) (2026-09-01)


### Features

* add append mode to plan_update_item for narrative sections ([d32851e](https://github.com/Audumla/AUDiaGentic/commit/d32851ed49a69ce97248b1b933944bdc0dc680a2))
* add gateway resume and provider surface updates ([df5a945](https://github.com/Audumla/AUDiaGentic/commit/df5a94569ef4bfc95fd385a1d2d4db0e47aed1b7))
* add generic hindsight recipe templates ([75dc6bd](https://github.com/Audumla/AUDiaGentic/commit/75dc6bd279f044961f52a0766429949de86c41ac))
* add gpt-auto contract-version schema migration v1 -&gt; v2 (GP21) ([b99dd76](https://github.com/Audumla/AUDiaGentic/commit/b99dd764e97d8b518f1c0bb8b0bd4806120f7fb7))
* add gpt-auto-t1/t2 test-project providers via adapter-hook dispatch ([c5d3a74](https://github.com/Audumla/AUDiaGentic/commit/c5d3a74208d88bc43c72f4069184ac1470a596e9))
* add packaged defaults + sparse project-overlay config resolution for gpt-auto (GP20) ([dd156c3](https://github.com/Audumla/AUDiaGentic/commit/dd156c3750e4cd0ddbdb2f2f2d99963f60211d15))
* add provider install adapters for opencode and pi ([dc8c827](https://github.com/Audumla/AUDiaGentic/commit/dc8c8271f72f2b058726bcaaf0190f89ae36e416))
* advance session platform implementation ([149d15a](https://github.com/Audumla/AUDiaGentic/commit/149d15a069ecd74215a94ed9e99ebcc6279ae71c))
* agent execution gateway rename, execution profiles, AgentTask API, provider reconciliation, project surfaces, and agents reorg ([4a52979](https://github.com/Audumla/AUDiaGentic/commit/4a52979c2ea4b470007f20fe5045578a5f431c96))
* **agents:** add canonical prompt profiles and templated prompts ([64455bd](https://github.com/Audumla/AUDiaGentic/commit/64455bda2197cd48110bca517d6311646e08952d))
* AS40 Pi RPC observation tap (chg_20260728_122457) ([ba09b71](https://github.com/Audumla/AUDiaGentic/commit/ba09b714dd391709f002a9ff8faec3858ccb7cbe))
* **AS59,AS76:** compose process startup from configuration instead of import-time wiring ([7d7c5ec](https://github.com/Audumla/AUDiaGentic/commit/7d7c5ec9c8dd7e025e879997714b65c8fb894170))
* capability catalogue tier rename and merged families support (PC01/PC02) ([93f1b12](https://github.com/Audumla/AUDiaGentic/commit/93f1b12eba8935a2a12130add22cd52bc1e2c705))
* CDP client gains event-based waitForFunction/waitForSelector [chg_20260808_130350] ([c77925f](https://github.com/Audumla/AUDiaGentic/commit/c77925f07aa76cfe400de599ff80b1c5a4dc4592))
* centralize lint projection and coding LSP cache ([99dd8ef](https://github.com/Audumla/AUDiaGentic/commit/99dd8efdc7186241ac94753b875558e0a78b3959))
* compute resource taxonomy — operator-declared GPUs & model instances [AS101] ([5609b30](https://github.com/Audumla/AUDiaGentic/commit/5609b305034976f1c05fea04415e1a76c02c76f6))
* cross-harness model availability overview API + MCP tool (MO20) ([2c26fb4](https://github.com/Audumla/AUDiaGentic/commit/2c26fb47fc6d61f3b25415a25e67a13c4635cfe2))
* declarative hindsight provisioning with recipe-based managed MCP ([236e41c](https://github.com/Audumla/AUDiaGentic/commit/236e41c8b888890450245ad89489c479d92df82c))
* default plan_update_item's notes field to append ([5a3da43](https://github.com/Audumla/AUDiaGentic/commit/5a3da434a35d55d2564e2dd61b4e0124828f35a3))
* execution profile surface naming & seeded agent definitions [AS82, AS83] ([44a7c07](https://github.com/Audumla/AUDiaGentic/commit/44a7c07bd91de07b12ae76425732726606e5b927))
* expose ordered assistant-message sequence in ChatSnapshot (GP08 slice 1) ([f704356](https://github.com/Audumla/AUDiaGentic/commit/f704356214de307dd31697f06e3a751652afa474))
* gateway lifecycle management & activity-verified watchdog [SH10, SH11, SH22] ([ad56600](https://github.com/Audumla/AUDiaGentic/commit/ad56600ad487e2a68a491959cf6d249de207c199))
* **gateway:** enforce negotiated slim status and response boundary ([6f3a1ca](https://github.com/Audumla/AUDiaGentic/commit/6f3a1ca2f317a342f28ba40b2736900debc5cbc6))
* GPT Auto session metadata persistence & nonblocking MCP status [AS82] ([be93362](https://github.com/Audumla/AUDiaGentic/commit/be933626029774b47b2d5c1de606c8bcee3e4737))
* gpt-auto browser provider — ChatGPT automation via CDP (BR01/BR02/BR03/BR04/GP01/GP02) ([3517891](https://github.com/Audumla/AUDiaGentic/commit/3517891cab32fc8f7c3e3fc9c229dede75a9d907))
* gpt-auto in-progress signals and reliable turn completion through agent MCP ([d73ea94](https://github.com/Audumla/AUDiaGentic/commit/d73ea949704ab6b4547bd1b318bb0cc7b23708e7))
* implement gpt-auto ChatGPT provider via CDP browser automation ([add02be](https://github.com/Audumla/AUDiaGentic/commit/add02be427fc34f4f63238fa84f97610ffc3dd79))
* implement shared PromptFingerprint primitive, migrate all 5 call sites (GP25) ([28e82dc](https://github.com/Audumla/AUDiaGentic/commit/28e82dce2098c6bb04a59fafa500de37cd0fafaa))
* ledger MCP — get_pending_events, batch record, get_fragment (CC49) ([ee81d4e](https://github.com/Audumla/AUDiaGentic/commit/ee81d4e37342c765a8d7c4ca1176bdc37af63c97))
* model capacity via provider model-source config & free-instance dispatch [AS101, AS105] ([e372b8d](https://github.com/Audumla/AUDiaGentic/commit/e372b8d6b6fa19445c93bbda1a53247cb8a99fab))
* opencode upgrade recipe live test infrastructure ([f3ca583](https://github.com/Audumla/AUDiaGentic/commit/f3ca583b45820ad70359581695f0b79a303ed74c))
* pi rpc tap for ACP bridge probing + remove prompt_injections ([0ad2276](https://github.com/Audumla/AUDiaGentic/commit/0ad2276a8f74d38f5ebd068f1e5a105c69a8f476))
* planning section serialization and hindsight fixes (DE04) ([16ff1a2](https://github.com/Audumla/AUDiaGentic/commit/16ff1a225bde6f013725ec2b6604bcb206d90950))
* recipe upgrades report availability + safe llama.cpp staging (chg_20260728_122828) ([50850c4](https://github.com/Audumla/AUDiaGentic/commit/50850c4d426e5d71bbe133bccae2abc525ed8d58))
* rig embedded recipe + e2e test infrastructure ([e4ca843](https://github.com/Audumla/AUDiaGentic/commit/e4ca8433ea89a4c2440bf48f14df3857f1d5cb1b))
* unify gpt-auto DOM message extraction into one true-order sequence (GP29) ([4265a8c](https://github.com/Audumla/AUDiaGentic/commit/4265a8c1bb1d0c001be29928b385c19ab0089041))


### Bug Fixes

* agent_task_wait returns status + progress on timeout instead of crashing ([29195fd](https://github.com/Audumla/AUDiaGentic/commit/29195fdd8a7aebd3ca22bca89b6dc244725d393f))
* **agents:** keep hosted context resolution global ([7688c63](https://github.com/Audumla/AUDiaGentic/commit/7688c63ce5f8bbcf0ec90c0c44652136dedefa29))
* **AS71,TE02:** hook sync, interaction export, pathlib compatibility, and planning sync fixes ([ec6a15c](https://github.com/Audumla/AUDiaGentic/commit/ec6a15c924cd5c05f9fa93989c0e636b0d479642))
* bounded retry for composer submit action (GP11), close GP15/GP17 ([d05d141](https://github.com/Audumla/AUDiaGentic/commit/d05d141ad75664f9a9eaeefcbf41d36ebef5ff64))
* bounded settle-wait before submission (GP11) ([47ffdde](https://github.com/Audumla/AUDiaGentic/commit/47ffdde62b931c9e2f3111cd190edb27d848ec84))
* classify provider surface probe failures ([1022d55](https://github.com/Audumla/AUDiaGentic/commit/1022d55236f5c4f9126d8fec798d73616f7a7edf))
* correct actively-false "no prompt was sent" recovery wording ([36a7826](https://github.com/Audumla/AUDiaGentic/commit/36a782684cbacdf823527abf0322cf07501e4f34))
* correlate gpt-auto responses against the request's own prompt span, not conversation-latest (GP30) ([7e46f65](https://github.com/Audumla/AUDiaGentic/commit/7e46f6548ae46529772e92f3ab15a175a31e29be))
* error code catalogue, planning idempotency, Cline capability matrix ([6af4fab](https://github.com/Audumla/AUDiaGentic/commit/6af4fab8370505233851f26b6ceb8b322901f667))
* expose actionable gpt auto recovery details ([4cd32b1](https://github.com/Audumla/AUDiaGentic/commit/4cd32b1c1ad61acd883711f4df5298be6c49d5a2))
* from_project_dict() silently discarded project overrides when given an unwrapped settings dict ([2b7dcf3](https://github.com/Audumla/AUDiaGentic/commit/2b7dcf34cdf006c2a4fba7f8bc7c647c15bbd514))
* **gateway:** carry prompt profile through service boundary ([0354bf9](https://github.com/Audumla/AUDiaGentic/commit/0354bf93b6a418d09e13c2bfab10430ef07239de))
* **gateway:** enforce global profile authority ([126f286](https://github.com/Audumla/AUDiaGentic/commit/126f286fa80791f55b82a681ba6992edded26694))
* **gateway:** keep diagnostics projection authoritative ([15038fb](https://github.com/Audumla/AUDiaGentic/commit/15038fb9e5866725fea160e23e634b3507921814))
* GPT Auto browser sessions no longer stall mid-answer [chg_20260809_012101] ([903a183](https://github.com/Audumla/AUDiaGentic/commit/903a183061e57ca4c7b0174fbd340f0139be932b))
* GPT Auto DOM reader — retry on detached execution context [chg_20260808_130418] ([4a47f25](https://github.com/Audumla/AUDiaGentic/commit/4a47f251167b130feac7908fde89157c8cca266e))
* GPT Auto session opens no longer fail with opaque timeout, evaluate tolerates navigation [chg_20260809_041147] ([127fdbb](https://github.com/Audumla/AUDiaGentic/commit/127fdbba77602e4823cd22cdbca447866a14821e))
* GPT Auto turns can no longer hang forever — absolute turn ceiling [chg_20260809_025808] ([ce25475](https://github.com/Audumla/AUDiaGentic/commit/ce254757e11d7aa9dda2b2f6efd76baa77971977))
* gpt-auto session transport response detection + adapter refactor (BR04) ([20a1f09](https://github.com/Audumla/AUDiaGentic/commit/20a1f095526b8a63582296989f5526a4f96e33c1))
* **gpt-auto:** connect via DevToolsActivePort when CDP discovery is refused ([0660f63](https://github.com/Audumla/AUDiaGentic/commit/0660f63a296466b1292d0836f7219a97d654564c))
* **gpt-auto:** resilient packaging, browser recovery, and completion detection ([f2b8908](https://github.com/Audumla/AUDiaGentic/commit/f2b8908a22649eb2e9ebc76036d785be12ad1d3e))
* harden error handling in gateway session dispatch and provider boundaries ([9348b27](https://github.com/Audumla/AUDiaGentic/commit/9348b2753a1c5e219397ca2e52fd93086e2655bb))
* harden optional integration boundaries ([e72f94d](https://github.com/Audumla/AUDiaGentic/commit/e72f94dd7c19d9090e2f4802ccda3eeececb0fb5))
* honor response-stall-timeout=0 (disabled) across every observation phase ([321561b](https://github.com/Audumla/AUDiaGentic/commit/321561b99d0e5d084422fee8dd32029695bd860b))
* immediate error-contract, Windows subprocess cleanup, architecture-test & planning-integrity [chg_20260809_001907] ([5d48187](https://github.com/Audumla/AUDiaGentic/commit/5d4818780ddb6ee642bf6867e737fc3ee1e891f6))
* independent submission-proof starvation fix + correlation truncation bound (GP19) ([db6b5c5](https://github.com/Audumla/AUDiaGentic/commit/db6b5c54e30b7e356d035f28763c391f669f396a))
* LSP hook removal on uninstall + opencode language keys to YAML (LSP23/LSP24) ([1aaf60a](https://github.com/Audumla/AUDiaGentic/commit/1aaf60a8c9414aa5a2c112be58f7c4cbcd5207e9))
* migrate gateway execution sessions to v3 contract [chg_20260809_114909] ([09a7606](https://github.com/Audumla/AUDiaGentic/commit/09a760614cefc2bf678284e672fbefe7cb24088d))
* OpenCode provider lifecycle — MCP refresh, model projection, Hindsight recipe, reconciliation ([1f0f494](https://github.com/Audumla/AUDiaGentic/commit/1f0f4947d7c399718d02827fe55f2f66352b119b))
* pick deterministically among duplicate-tab matches (GP04) ([926ffac](https://github.com/Audumla/AUDiaGentic/commit/926ffac42b733aa212e84c877fdbba50c1043081))
* planning section parser & ACP transport improvements [AS88] ([6488a15](https://github.com/Audumla/AUDiaGentic/commit/6488a15d5234bad7c1fa98d0291a594318e37306))
* **planning:** serialize concurrent document writes ([e28dbaa](https://github.com/Audumla/AUDiaGentic/commit/e28dbaaf7cbf98823bc060f23856720207b625bc))
* preserve actionable gpt auto error diagnostics ([9e474de](https://github.com/Audumla/AUDiaGentic/commit/9e474de86afbad246df416ac5c12d02c1a6fa588))
* preserve fenced code-block language tag as visible text in prompt normalization ([d7e3a80](https://github.com/Audumla/AUDiaGentic/commit/d7e3a8092ebfe851adfed1c6171c0887a6d9951c))
* raise GPT Auto session open timeout to 420s & sync ledger ([343332c](https://github.com/Audumla/AUDiaGentic/commit/343332c938f424b8df3bfebca4f752c4f9d568a7))
* reconcile pending gpt auto status ([47cb9b9](https://github.com/Audumla/AUDiaGentic/commit/47cb9b99be76aa322d72dcb844835c979095b00b))
* replace gpt-auto's fixed submission-proof deadline with an activity lease ([fb981ca](https://github.com/Audumla/AUDiaGentic/commit/fb981caf97a3b9f637d17c5f251a9970e5cef1b2))
* require completion-control AND message-finalized together (GP17) ([aa756bf](https://github.com/Audumla/AUDiaGentic/commit/aa756bf44b2c679790434e24523076cbddd5418f))
* rewire gpt-auto response-completion through the shared observation engine ([f2f65e9](https://github.com/Audumla/AUDiaGentic/commit/f2f65e912cb245928535c73a3bf73ab65075ce7e))
* schema-path resolution bugs after provider services reorganization ([9d73319](https://github.com/Audumla/AUDiaGentic/commit/9d73319c0834cbddd3701cc6c5f40aa99186e743))
* self-heal gateway client cache on NET-AGSV-002 (GP06) ([2c51c3c](https://github.com/Audumla/AUDiaGentic/commit/2c51c3c30e0779acf7bd6ef0c7380396f8b5390d))
* session open timeout no longer leaks orphan sessions [chg_20260809_041201] ([a445404](https://github.com/Audumla/AUDiaGentic/commit/a445404a3fafcbed3b53c282284608ca93a8cc59))
* stop forcing idle gpt-auto chats to immediately reopen closed tabs ([1a4eb01](https://github.com/Audumla/AUDiaGentic/commit/1a4eb0157bb60f0c0c0f03071d0174720f04bd81))
* stop letting a stuck DOM widget veto gpt-auto turn completion ([7bd5643](https://github.com/Audumla/AUDiaGentic/commit/7bd56436e12d8b995cff36e149f75b81080ac49f))
* stop resume hanging when a bridge replacement races the open path ([142bb54](https://github.com/Audumla/AUDiaGentic/commit/142bb540747b4e0320cd14b939834b55effc3cc7))
* track unregister_chat's background status-refresh task (GP18, partial) ([b46de76](https://github.com/Audumla/AUDiaGentic/commit/b46de76565cc14b5e17666cf43619cc28e7d2076))


### Documentation

* add AS59 to simplify validation tracking (chg_20260728_222250) ([04488ec](https://github.com/Audumla/AUDiaGentic/commit/04488ecc7ec4255ef222b76f750ffaf0ea514cd4))
* add GP17 (false-positive early completion), correct GP10, refine GP16 ([cd3d315](https://github.com/Audumla/AUDiaGentic/commit/cd3d31579b4d192493bf1389a07988ef52071509))
* add gpt auto lifecycle operations plan ([c7a8c2c](https://github.com/Audumla/AUDiaGentic/commit/c7a8c2c63087dae80743ab3eb3cd78bb4732af04))
* agent session planning review — corrected references & closed items [chg_20260809_012118] ([09f5590](https://github.com/Audumla/AUDiaGentic/commit/09f559076f80f4011f2f68748dd1ad293d73651f))
* **agent-sessions:** build delegation on runtime gateway access ([b584bb6](https://github.com/Audumla/AUDiaGentic/commit/b584bb617cd06c1323177574c71e1e17664122b4))
* **agent-sessions:** correct gateway MCP runtime boundary ([01b2bc0](https://github.com/Audumla/AUDiaGentic/commit/01b2bc0cd41e32324796b082ae070d0ab42af98f))
* **agent-sessions:** scope runtime and operator gateway access ([06bcecd](https://github.com/Audumla/AUDiaGentic/commit/06bcecd059dc213152e0b693f42333b81cc55c26))
* **agents:** record AG16 implementation ledger ([c3f0c17](https://github.com/Audumla/AUDiaGentic/commit/c3f0c17526da9f1636b5e29bd872e6641a1dfff5))
* architecture review of cross-plan items — completed reviews & stale reference fixes [chg_20260809_025132] ([f60eb61](https://github.com/Audumla/AUDiaGentic/commit/f60eb612639e64fc7123fb91b2ddcf9dba201697))
* **AS59,AS61,AS77-AS79:** consolidate agent-role planning into single sequence ([cc3ae34](https://github.com/Audumla/AUDiaGentic/commit/cc3ae34c47c617903b1d8bc625d7fcdf6c864e40))
* assess GP09/GP06/GP08 for implementable slices, confirm GP06 wording fix already landed ([7f1cfd8](https://github.com/Audumla/AUDiaGentic/commit/7f1cfd8649ff053517cf5f335a2bdc080ff93204))
* break GP09/GP06/GP08/GP19 into sequenced, implementation-ready child plan items ([30479f8](https://github.com/Audumla/AUDiaGentic/commit/30479f8a32cd37a6bfcb18e9f392abf818e7e2df))
* capture gateway restart procedure and client cache bug (GP04/GP06) ([5254641](https://github.com/Audumla/AUDiaGentic/commit/52546416038f8b7a6b9931f535c787180239b963))
* capture GP05-GP08 review corrections and new PC14/GP08 items ([b1d3622](https://github.com/Audumla/AUDiaGentic/commit/b1d3622b8d6936c9d3f046a3af75bbaf5d114017))
* capture same-conversation duplicate-tab resume failure (GP04) ([00baf45](https://github.com/Audumla/AUDiaGentic/commit/00baf45782440d834d878eae6cf94701a0b2efc1))
* clean up managed mutation audit doc and add provider templates ([03eed31](https://github.com/Audumla/AUDiaGentic/commit/03eed31c9b1c3bfa171a0f8f3d77e21504f2f356))
* close GP03, split GP04's open findings into their own items ([1ae3b65](https://github.com/Audumla/AUDiaGentic/commit/1ae3b655fe254bb5cd1f40923bd5d16d843aa8f4))
* close GP05, record AR26, sync GP07/GP08 cross-references ([32dd79c](https://github.com/Audumla/AUDiaGentic/commit/32dd79c245fc4857c2dad869ab26093e7deeae7e))
* close GP07 (observation state machine validated live) ([1d7288d](https://github.com/Audumla/AUDiaGentic/commit/1d7288dbc2e6952154b7800cf81c8b70de3e3afa))
* close GP08 -- stated acceptance criterion met and regression-tested by GP30 ([e5909ef](https://github.com/Audumla/AUDiaGentic/commit/e5909ef7285285f7283e70964471626f4b66a522))
* close GP09 -- config-drift hazard fixed by GP20+GP21, drift-detection tooling remains as GP26 ([3931f38](https://github.com/Audumla/AUDiaGentic/commit/3931f38394d79472232daa9c6021c4fb74ead717))
* close GP11/GP12 (live-validated post gateway restart), GP16 (superseded by GP17) ([da79bf5](https://github.com/Audumla/AUDiaGentic/commit/da79bf59476be46ad3f9bb0b432405b6e5952611))
* close GP19 -- all three required fixes complete, root cause resolved by GP25 ([86073de](https://github.com/Audumla/AUDiaGentic/commit/86073de0a16add087c70a3fdcc3ecd6281d3ced8))
* close GP23 -- already implemented and tested under the GP06 investigation ([3aee706](https://github.com/Audumla/AUDiaGentic/commit/3aee7069666f5281bf45865fe93cfd3e33185b69))
* close GP25 -- live-validated fix for the hard block on gpt-auto reliability ([cb1d17b](https://github.com/Audumla/AUDiaGentic/commit/cb1d17b798bb77fb4b96f54352ca29b076703393))
* close PC06 + CC52, move reviews to completed ([46e0689](https://github.com/Audumla/AUDiaGentic/commit/46e06895e9eeb1d0d3b190556814d7d16c21c116))
* close PR04 + reassess AS40/PR08/PR09 + sync ledger ([df2dbdc](https://github.com/Audumla/AUDiaGentic/commit/df2dbdca11c339b2e57b1c6e2578ed6475121023))
* close PR08/PR09, move agent-sessions reviews to completed ([2eeb144](https://github.com/Audumla/AUDiaGentic/commit/2eeb14499dc81ff95e7612118e57fcf782416e01))
* confirm GP18's window-creation fallback works, narrow bug to the discovery-call hang ([79cc2a3](https://github.com/Audumla/AUDiaGentic/commit/79cc2a39a0271931a80290b3e8e817ce6e0209a1))
* fold code-level GP24/GP30 correlation design; record 3rd live GP19 confirmation ([e84a927](https://github.com/Audumla/AUDiaGentic/commit/e84a927942ee0bc1ab2e61bdfaae7f4d3da03841))
* fold GP06 design consultation, add GP13/GP14/GP15 ([d496cda](https://github.com/Audumla/AUDiaGentic/commit/d496cdad1f8a3e7241e7bff6cb8b22433fe4d72e))
* fold GP08 design consultation, add GP16, reconfirm GP06 finding ([e9ad0eb](https://github.com/Audumla/AUDiaGentic/commit/e9ad0eb39229c09d68592bb9a27ce80a8bd9be6c))
* fold GP09 design consultation, second GP11 reproduction ([ff74ace](https://github.com/Audumla/AUDiaGentic/commit/ff74aceceb237ddd69c0c2a613bbe158671ddab5))
* fold GP10 rate-limit-recovery consultation; record live GP19 reconciliation-gap confirmation ([0c9e8da](https://github.com/Audumla/AUDiaGentic/commit/0c9e8dae26a6af73d03214f61177b7110733f070))
* fold GP14 consultation on V4 public response-schema redesign ([322352f](https://github.com/Audumla/AUDiaGentic/commit/322352fc8d081aff95939d7fb3b911273227c2c5))
* fold GP19 design consultation ([76b53c1](https://github.com/Audumla/AUDiaGentic/commit/76b53c18aa05a29f2c6826a6a11a3eb8dc67ae79))
* GP12 static trace rules out both original hypotheses ([9c34975](https://github.com/Audumla/AUDiaGentic/commit/9c3497575a6a2a6dac943677e44f552ce0a6d639))
* GP18 -- rule out connection accumulation via live TCP capture during the actual hang ([922c035](https://github.com/Audumla/AUDiaGentic/commit/922c0351e5aa88c5bdef39d9c457af37c3236dbc))
* GP19 gains concrete real-incident evidence from a live bigcherry session ([34b4c30](https://github.com/Audumla/AUDiaGentic/commit/34b4c30a177e4ec35a10aec6e7dde1f30cc49689))
* GP27 crash-repro rules out atomic-write-tearing; GP18 gets a strong new event-loop-ownership hypothesis ([6d0a810](https://github.com/Audumla/AUDiaGentic/commit/6d0a8102d19908a95db788a7fdee0deb68a1a181))
* GP31 -- manual-bypass hypothesis falsified, browser killed by a clean gateway_restart() call too ([4840743](https://github.com/Audumla/AUDiaGentic/commit/4840743df3e09ad3dad637710db3f74ed309ef14))
* GP31 -- ruled out process ancestry, gpt_auto's own shutdown code, ([28e82dc](https://github.com/Audumla/AUDiaGentic/commit/28e82dce2098c6bb04a59fafa500de37cd0fafaa))
* log connection-accumulation hypothesis for GP18, needs a during-the-hang check ([c496a0d](https://github.com/Audumla/AUDiaGentic/commit/c496a0dbceceb92c79cd1098289f2fd59781a0af))
* move completed plan items and reviews to completed/ ([482ca76](https://github.com/Audumla/AUDiaGentic/commit/482ca7651c8e19becff1bd5168c110fe032129b2))
* move completed plan items from active to completed ([78ecaa0](https://github.com/Audumla/AUDiaGentic/commit/78ecaa00f0e1eff05b4d7864a6415ef611218279))
* new plan items (CC50-CC52, PR08-PR09) + sync release ledger ([eb5ec9b](https://github.com/Audumla/AUDiaGentic/commit/eb5ec9b342458d99da491ee2c725095182eac777))
* plan item reassessments + sync release ledger ([f773c37](https://github.com/Audumla/AUDiaGentic/commit/f773c37ca2c76f6a074c4b7311b9d8c0fea60a37))
* **planning:** add A2A agent and task surface plan ([b8fae6e](https://github.com/Audumla/AUDiaGentic/commit/b8fae6e523dbcf0b773302e7b3c491ea328b3818))
* **planning:** add agent runtime refactor execution order ([df046ef](https://github.com/Audumla/AUDiaGentic/commit/df046ef7ccebebe890cee33ac44e2fb9611af8be))
* **planning:** add agent task contract migration plan ([1983195](https://github.com/Audumla/AUDiaGentic/commit/19831959f68410eb6cac0c4bfd99f8f7e38d2b18))
* **planning:** add code-proven MCP disposition to AS59 ([37e2f4f](https://github.com/Audumla/AUDiaGentic/commit/37e2f4f9df000ca52b177ed2fd47605d845c51cd))
* **planning:** add DI-ready boundary to AS60 ([2f257dc](https://github.com/Audumla/AUDiaGentic/commit/2f257dcaa46d0757dc1ae5b897391b4e5078f08d))
* **planning:** add DI-ready boundary to AS61 ([373c475](https://github.com/Audumla/AUDiaGentic/commit/373c475f5511dd3eb826cda851d237614e37a4eb))
* **planning:** add effective capability composition plan ([4fbb37f](https://github.com/Audumla/AUDiaGentic/commit/4fbb37f559d42e8a322907d1034e146aad9de1e1))
* **planning:** add execution profile terminology refactor ([982e9bd](https://github.com/Audumla/AUDiaGentic/commit/982e9bdc4f9fb9df1e2f2e53988517881fe116d7))
* **planning:** add external ACP facade plan ([05289bf](https://github.com/Audumla/AUDiaGentic/commit/05289bf36d5b0dc6a22ab6448672494903710ef4))
* **planning:** add harness delegation matrix and sequence AS66 after AS65 ([8fb78ca](https://github.com/Audumla/AUDiaGentic/commit/8fb78ca9e8f3362400a304fa066b8e6a1e2a9a1f))
* **planning:** add logical agent definition composition plan ([59303a0](https://github.com/Audumla/AUDiaGentic/commit/59303a0f7793a400422e5fdfdfd3256115f57bf7))
* **planning:** add reusable role contracts plan ([83a4c12](https://github.com/Audumla/AUDiaGentic/commit/83a4c1203b7c7f46045c8ccae4f4d1e94f3d4c73))
* **planning:** align AS19 with layered agent architecture ([ee38826](https://github.com/Audumla/AUDiaGentic/commit/ee3882674cf310e860b42713b7d1354af074ba50))
* **planning:** align AS29 with execution profiles and agent composition ([7d9dc15](https://github.com/Audumla/AUDiaGentic/commit/7d9dc15fb5f1fb51214ea8b1eb414a6aaa4f553b))
* **planning:** align AS30 bindings with layered agent snapshots ([15e7635](https://github.com/Audumla/AUDiaGentic/commit/15e763506414bd09781e2b574a979ecc7d5a07d8))
* **planning:** align AS31 output authority with ACP and A2A adapters ([61ceeac](https://github.com/Audumla/AUDiaGentic/commit/61ceeac060503047099414914cbc9ecc6c82e6d0))
* **planning:** align AS47 continuation with immutable agent composition ([8024bdf](https://github.com/Audumla/AUDiaGentic/commit/8024bdffbe27031772400ff185f09fe88bf254f4))
* **planning:** align AS49 resume with immutable agent composition ([fc6182c](https://github.com/Audumla/AUDiaGentic/commit/fc6182cb2fe0357ecb967a2724c45038acdec2da))
* **planning:** align AS57 as protocol-neutral read authority ([db09d3d](https://github.com/Audumla/AUDiaGentic/commit/db09d3dc3fe0b23ee66bbff04b037656409ee7e7))
* **planning:** align AS58 as protocol-neutral control authority ([58fe7df](https://github.com/Audumla/AUDiaGentic/commit/58fe7dfae917b9b023ea8f497a20b8429c00b7eb))
* **planning:** align AS60 with current profile authorities ([debd2f1](https://github.com/Audumla/AUDiaGentic/commit/debd2f171446d8a644b18327c11267e6e80d1e95))
* **planning:** align AS60 with management and runtime MCP code ([b7756aa](https://github.com/Audumla/AUDiaGentic/commit/b7756aa6c240e1d30921b49f0f83efe44f23b726))
* **planning:** align AS63 with current gateway API structure ([7303408](https://github.com/Audumla/AUDiaGentic/commit/73034089bca3e5545107298499d01b0ff97bd91a))
* **planning:** align AS63 with gateway client and MCP boundaries ([9a2f383](https://github.com/Audumla/AUDiaGentic/commit/9a2f383151b14455a22d27b6f087a199c2a0a9dc))
* **planning:** apply bounded legacy exemption to AgentTask migration ([93bfbd2](https://github.com/Audumla/AUDiaGentic/commit/93bfbd20fb861393057fad792b47a829af0f9c8f))
* **planning:** apply bounded legacy exemption to AS60 ([f22fb02](https://github.com/Audumla/AUDiaGentic/commit/f22fb02457db7d185dc3b856745df9bc82aa6792))
* **planning:** block AS60 on AS59 Gate 0 ([47d829c](https://github.com/Audumla/AUDiaGentic/commit/47d829cc46fafc49d076eeaeb17440e654036806))
* **planning:** bound legacy host and slim composition migration ([f873eaa](https://github.com/Audumla/AUDiaGentic/commit/f873eaaeebea2dc95e254637766722839e21851c))
* **planning:** clarify execution profile management surface ([626cf20](https://github.com/Audumla/AUDiaGentic/commit/626cf205ffe9ca8521f797270180511e6c93d282))
* **planning:** complete CC64 prompt authority cleanup ([2f2044d](https://github.com/Audumla/AUDiaGentic/commit/2f2044db151b58a7d8ed80bc3cef9b979cfef807))
* **planning:** compose Agent Definition services through foundation bootstrap ([6afe6ab](https://github.com/Audumla/AUDiaGentic/commit/6afe6abf0e2a551eb7a9fe36934bc0f0ae25ea07))
* **planning:** defer agent tool policy to harness defaults ([032e49d](https://github.com/Audumla/AUDiaGentic/commit/032e49de2aa5e4b451713fc474a5219bbea201c4))
* **planning:** define delegation as runtime capability surface ([1715500](https://github.com/Audumla/AUDiaGentic/commit/171550076d451850b9a4b456e8feaf4121436138))
* **planning:** detail runtime delegation and A2A boundaries ([605bd0a](https://github.com/Audumla/AUDiaGentic/commit/605bd0a9c77d8211688db22cc537a16e49a34471))
* **planning:** distinguish management and runtime MCP surfaces ([eaed21d](https://github.com/Audumla/AUDiaGentic/commit/eaed21d94c4167e6fbbe1a865399f9f662542c58))
* **planning:** enforce direct migrations in AS59 ([2dc4906](https://github.com/Audumla/AUDiaGentic/commit/2dc4906a59c0605837d0d7988b2564f75dc5b4cd))
* **planning:** exclude tool policy from capability checks ([fa2a291](https://github.com/Audumla/AUDiaGentic/commit/fa2a291d6de7c342e7066f132883ba1d8c1f38a7))
* **planning:** expand AS59 Gate 0 execution work package ([949e427](https://github.com/Audumla/AUDiaGentic/commit/949e427abff10fb23a0d8f9d86b847308d1cd6be))
* **planning:** keep role tooling as placeholder only ([6e24cb9](https://github.com/Audumla/AUDiaGentic/commit/6e24cb9efd4f5607d47b3efd4b8ae09303205a7f))
* **planning:** keep roles out of runtime MCP ownership ([48b2e39](https://github.com/Audumla/AUDiaGentic/commit/48b2e39eeb1b8b5bba6aa9587b003b8b28685cd3))
* **planning:** make AgentTask the sole work API ([1941eed](https://github.com/Audumla/AUDiaGentic/commit/1941eedf0682e8c379a9a733c1a9f8b267dace4c))
* **planning:** make AS59 authoritative alignment and contradiction gate ([95df0df](https://github.com/Audumla/AUDiaGentic/commit/95df0dfab9a7145264bf9eefe3250619b23e3ed8))
* **planning:** make AS59 the sole start and consolidation authority ([f8a990e](https://github.com/Audumla/AUDiaGentic/commit/f8a990ef71c69c4d153f0e898d363629021cb46a))
* **planning:** make AS60 a direct profile migration ([7a21e5f](https://github.com/Audumla/AUDiaGentic/commit/7a21e5ffc39470f39786d3a569f7ea27d6d82c9a))
* **planning:** make composition root config-driven ([1941c2f](https://github.com/Audumla/AUDiaGentic/commit/1941c2fc337e7620c5d24f0f35caf7761609ee8e))
* **planning:** preserve IoC service boundaries in slim agent plans ([31752bd](https://github.com/Audumla/AUDiaGentic/commit/31752bd7613ae06c28e388cb91ca2cd3bb4e7884))
* **planning:** reduce capability work to admission checks ([b5c4cd6](https://github.com/Audumla/AUDiaGentic/commit/b5c4cd6b3163e429b9f5aba0660630fa18755864))
* **planning:** remove migration path from AS62 ([be77864](https://github.com/Audumla/AUDiaGentic/commit/be7786432f28905dc44e51f19ccabdb7b13f9290))
* **planning:** route capability inputs through foundation composition ([fb45928](https://github.com/Audumla/AUDiaGentic/commit/fb459281ef13c4dc8968fb1b5bf55ee859900ab6))
* **planning:** separate agent publication from runtime tool materialization ([5e87da1](https://github.com/Audumla/AUDiaGentic/commit/5e87da1a28365f320db1af426687136940baed56))
* **planning:** sequence AS61 after AS60 R1 ([5832ce4](https://github.com/Audumla/AUDiaGentic/commit/5832ce487e8194f4886f12c29d4df3bc8d3eb474))
* **planning:** sequence AS62 after AS61 R2 ([467ba59](https://github.com/Audumla/AUDiaGentic/commit/467ba592a65f1e143ea63b37153a20273b2c5a28))
* **planning:** sequence AS63 after AS62 R3 ([2d73a76](https://github.com/Audumla/AUDiaGentic/commit/2d73a7689dd03bba59ccf365034da738db433c98))
* **planning:** sequence AS64 after AS63 R4 ([877f264](https://github.com/Audumla/AUDiaGentic/commit/877f26401affb54298d4e91a4008ff9f2ff439ba))
* **planning:** sequence AS65 after AS64 R5 ([f667a2e](https://github.com/Audumla/AUDiaGentic/commit/f667a2e74496c1ac583bc9000c0306d2decb1589))
* **planning:** simplify AgentTask to existing request identity ([059a5cd](https://github.com/Audumla/AUDiaGentic/commit/059a5cd21e44a94a36e735ce5e1a0b273742a718))
* **planning:** simplify layered agent architecture plans ([0d5c0b2](https://github.com/Audumla/AUDiaGentic/commit/0d5c0b2ecda57165e9756d1542b4f38ef49261bc))
* **planning:** slim AS60 execution profile refactor ([c775d8b](https://github.com/Audumla/AUDiaGentic/commit/c775d8b9d4d5419acdde9b07506aa63369eabfad))
* **planning:** slim AS61 role plan ([47735c9](https://github.com/Audumla/AUDiaGentic/commit/47735c9637d5b8f006f724e12d3bcc9b3dea3305))
* **planning:** slim AS62 and preserve DI service boundaries ([e3544b7](https://github.com/Audumla/AUDiaGentic/commit/e3544b7fd14def972aceb713511b71510f32ac03))
* **planning:** slim AS63 task service boundary ([892e543](https://github.com/Audumla/AUDiaGentic/commit/892e543c212c7fcfad97d1db9e2a606998cb2a4f))
* **planning:** slim AS64 capability checks ([3eb49d0](https://github.com/Audumla/AUDiaGentic/commit/3eb49d03054610ab3a796442ed4b56ffc193f6e6))
* **planning:** slim AS65 ACP adapter plan ([8811e06](https://github.com/Audumla/AUDiaGentic/commit/8811e0614b3bf2f8d0ebcf462814df256bbe2f75))
* **planning:** slim AS66 A2A and delegation plan ([c0a5bea](https://github.com/Audumla/AUDiaGentic/commit/c0a5bea15e1b327c667029fc069fa4617159cf34))
* **planning:** tighten A2A and delegation boundaries ([b88d28c](https://github.com/Audumla/AUDiaGentic/commit/b88d28c0cadeb0952c5848d174a58ad5a5d83525))
* **planning:** tighten ACP adapter scope and ownership ([6074600](https://github.com/Audumla/AUDiaGentic/commit/6074600261f4faaa3de8ba618ac8c31db278148b))
* **planning:** tighten agent definition composition plan ([02c769f](https://github.com/Audumla/AUDiaGentic/commit/02c769f57477591348fc9af046cea576f05c499e))
* **planning:** tighten role ownership and service boundary ([821a4eb](https://github.com/Audumla/AUDiaGentic/commit/821a4eb1ce031e6753dfbaa5847ce44d7aa15af3))
* **planning:** wire ACP adapter through foundation composition ([e53f856](https://github.com/Audumla/AUDiaGentic/commit/e53f85649fb51686bd14df3f0dbeb911462878bc))
* **planning:** wire delegation and A2A through foundation composition ([112f73b](https://github.com/Audumla/AUDiaGentic/commit/112f73b137f466a5c6e2de678a33a129e29641a8))
* **planning:** wire Role services through foundation composition ([5dccc74](https://github.com/Audumla/AUDiaGentic/commit/5dccc741cedc0970fbdb8ba52bca23c042429246))
* prepare AS59 composition gate ([563d12d](https://github.com/Audumla/AUDiaGentic/commit/563d12d4f9498e5fa808f68bf0cb43cf7c68caa3))
* provider-capability-model planning items PC08-PC13 + reviews ([f0c2af8](https://github.com/Audumla/AUDiaGentic/commit/f0c2af867a0254002c174ca7533a8d9302ec98a0))
* reassess agent-sessions plan items + provider capability model (chg_20260728_114857) ([2a631f7](https://github.com/Audumla/AUDiaGentic/commit/2a631f793148d5011da2bb1dc712062ee85e0f61))
* recipe upgrade classification inventory (PR09, chg_20260728_121435) ([0a32306](https://github.com/Audumla/AUDiaGentic/commit/0a32306d06cc4cffe04bd3a159fa20c8564f7545))
* reclassify GP18 as a real availability gap, not a test flake ([7eb2779](https://github.com/Audumla/AUDiaGentic/commit/7eb27790604b43c199eb13a783ae937887385567))
* record GP10 consultation as unrecoverable, resubmit fresh ([089a265](https://github.com/Audumla/AUDiaGentic/commit/089a26529ae1136716effdb3c0604fa3f4df8be4))
* record GP11 bounded-retry partial fix ([d0e430d](https://github.com/Audumla/AUDiaGentic/commit/d0e430d947d5a1a93339e4ebc5505443ca8b24d2))
* record GP18 investigation findings, live validation incomplete ([c02e344](https://github.com/Audumla/AUDiaGentic/commit/c02e344b14ef82f256202a04e8e77454c5303b23))
* record GP18 two-layer recovery design (discovery timeout + window-loss reconciliation) ([116162d](https://github.com/Audumla/AUDiaGentic/commit/116162d165e0a4a25c9fe8e1e3ed23e568bd0bb5))
* record GP19's two implemented fixes and the remaining open primitive work ([a365931](https://github.com/Audumla/AUDiaGentic/commit/a365931253af7921320016458c55aac840584653))
* record GP31 -- gateway restart workaround killed the running browser process ([8ef258a](https://github.com/Audumla/AUDiaGentic/commit/8ef258af50e69d39a208220504e36d9ba44d0719))
* refine planning process and normalize plan field naming across all items ([deedbfe](https://github.com/Audumla/AUDiaGentic/commit/deedbfe74a1483189952346daf9f842f86bf7ab9))
* restore GP11 notes lost to stale MCP server, fold GP13 consultation ([8ad9dd0](https://github.com/Audumla/AUDiaGentic/commit/8ad9dd080a50725341c47a3fda68e564fc73450e))
* restructure agent-sessions plan & compute resource taxonomy design [AS81-AS105, SH10-SH22] ([b06dab1](https://github.com/Audumla/AUDiaGentic/commit/b06dab1426c97eecd42e4c903add62e3b3436863))
* sync GP07 ledger-event linkage for the completion-heuristic fix ([c2d2636](https://github.com/Audumla/AUDiaGentic/commit/c2d2636be47e3c670209ea830a2a582825579518))
* sync GP07 ledger-event linkage for the response-completion engine fix ([594321a](https://github.com/Audumla/AUDiaGentic/commit/594321ac60b8a0c214ab1d90e457e33402f8490b))
* sync GP07 ledger-event linkage for the submission-proof fix ([6e3a31e](https://github.com/Audumla/AUDiaGentic/commit/6e3a31e1592a2850f6191dc1e7651db771a308da))
* sync ledger-event linkage; widen GP11 with recurring large-prompt evidence ([bbb512b](https://github.com/Audumla/AUDiaGentic/commit/bbb512bfad2dfeede0f2f6906067a034afcb15db))
* sync plan items and release ledger for GP04/GP05/GP06/GP07 ([3f8d626](https://github.com/Audumla/AUDiaGentic/commit/3f8d6262581d3d8539cf5b0c07399de46fceb479))
* synchronize planning state — move completed items, update ledger ([01272c8](https://github.com/Audumla/AUDiaGentic/commit/01272c8bf81e59980fefb8ba8286ca2255ec4b80))
* update AGENTS.md for ledger MCP tools + sync release ledger ([bfec8d1](https://github.com/Audumla/AUDiaGentic/commit/bfec8d198da2b52dc3997e14ceed45567e0c7162))
* update AS101 plan, close AS105 & add reviews [AS101, AS105] ([3aa2ce6](https://github.com/Audumla/AUDiaGentic/commit/3aa2ce6c9fef005631d684c0d6c8b910fdf80827))
* update documentation and move docker test isolation standard ([2ec3695](https://github.com/Audumla/AUDiaGentic/commit/2ec3695236677b1c18fcf5b2d0d825a02730f6c4))
* update plan item change logs and add CC48/DE04 plan items ([f0dcc7d](https://github.com/Audumla/AUDiaGentic/commit/f0dcc7df5ea2342d4e4980eb11c18e749816590e))
* update plan items + standards + sync ledger ([2a4ec87](https://github.com/Audumla/AUDiaGentic/commit/2a4ec8738fb672d1d0d92466544bae9796e4d5b2))
* update PR09 plan item status ([c2f0f96](https://github.com/Audumla/AUDiaGentic/commit/c2f0f96adf410f1a86fb71964be5f9c5262c0df7))

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
