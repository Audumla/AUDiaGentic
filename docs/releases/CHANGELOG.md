# Changelog

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
