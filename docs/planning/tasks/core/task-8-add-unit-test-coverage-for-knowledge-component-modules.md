---
id: task-8
label: Add unit test coverage for knowledge component modules
state: done
summary: Create unit tests for search, bootstrap, sync, config modules targeting 80%+
  coverage
domain: core
spec_ref: wp-13
standard_refs:
- standard-5
- standard-6
---




# Description\n\nAdd comprehensive unit tests for core knowledge component modules:\n\n1. **search.py** (136 lines) — Test filter_by_metadata, search_pages, scoring\n2. **bootstrap.py** (296 lines) — Test initialization, config loading, validation\n3. **sync.py** (546 lines) — Test file watch, sync operations, event emission\n4. **config.py** (311 lines) — Test config loading, schema validation, defaults\n5. **models.py** (111 lines) — Test SearchResult, page models\n\nTarget: 40+ unit tests, 80%+ code coverage for these modules.\n\n# Acceptance Criteria\n\n- [ ] Unit tests added to tests/unit/knowledge/ (new directory)\n- [ ] Test files: test_search.py, test_bootstrap.py, test_sync.py, test_config.py, test_models.py\n- [ ] Each module has tests for main functions and edge cases\n- [ ] Coverage report shows >80% for target modules\n- [ ] Tests run clean with pytest\n- [ ] No dependencies on external services (all mocked)\n\n# Notes\n\nDo not include tests for llm.py (leave for separate test work).\nUse fixtures for file I/O and config setup.\nSee standard-0006 for test structure expectations.\n"
