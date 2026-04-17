---
id: task-220
label: Add --guidance CLI parameter to tm.py
state: done
summary: Add --guidance argument to tm request command, validate against available
  guidance levels, pass to new_request()
spec_ref: spec-10
request_refs:
- request-11
standard_refs:
- standard-5
- standard-6
---







# Description

Add --guidance argument to tm.py request command. Validate against available guidance levels from config and pass to new_request() function.

# Acceptance Criteria

- [ ] --guidance argument added to argparse
- [ ] Choices: [light, standard, deep]
- [ ] Help text explains guidance levels
- [ ] Validation against config guidance_levels
- [ ] Error message for invalid value
- [ ] Passed to new_request() as guidance parameter
- [ ] CLI tested with all three values
- [ ] CLI tested with invalid value
- [ ] Backward compatible (no --guidance = standard)

# Notes

This task exposes guidance levels to users via the CLI.

# State

done
