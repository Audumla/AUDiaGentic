## Summary
The AUDiaGentic execution system manages workflow jobs, prompt processing, and job lifecycle operations. It provides the infrastructure for running tagged prompt workflows, controlling job execution, tracking job state, and bridging between different provider systems.

## Current state
**Execution System** (`src/audiagentic/execution/`):

**Job Management** (`src/audiagentic/execution/jobs/`):
- **Control** (`control.py`): Job lifecycle control (start, stop, status, list)
- **Records** (`records.py`): Job record management and persistence
- **Reviews** (`reviews.py`): Review workflow management
- **Release Bridge** (`release_bridge.py`): Bridge execution to release system
- **State Machine** (`state_machine.py`): Job state transitions and validation
- **Stages** (`stages.py`): Multi-stage job execution

**Prompt Processing** (`src/audiagentic/execution/jobs/`):
- **Prompt Launch** (`prompt_launch.py`): Launch jobs from prompts
- **Prompt Trigger Bridge** (`prompt_trigger_bridge.py`): Normalize and route tagged prompts
- **Prompt Parser** (`prompt_parser.py`): Parse prompt launch requests
- **Prompt Syntax** (`prompt_syntax.py`): Define and validate prompt syntax
- **Prompt Templates** (`prompt_templates.py`): Manage prompt templates

**Core Capabilities:**
- Job lifecycle: create, start, monitor, complete, cancel
- State machine: validated state transitions
- Prompt normalization: canonical tag processing
- Provider routing: route to appropriate provider
- Multi-stage execution: complex workflow orchestration
- Review workflows: integrate reviews into execution

**Integration Points:**
- Planning system: jobs create and update planning artifacts
- Runtime system: job state stored in jobs store
- Knowledge component: execution documented and synced
- Release system: jobs trigger release operations

## How to use
**Job Control:**

```python
from audiagentic.execution.jobs import control

## List all jobs
jobs = control.list_jobs()

## Get job status
status = control.get_job_status(job_id="job-123")

## Start job
control.start_job(job_id="job-123")

## Stop job
control.stop_job(job_id="job-123", reason="Cancelled by user")

## Cancel job
control.cancel_job(job_id="job-123")
```

**Prompt Launch:**

```python
from audiagentic.execution.jobs import prompt_launch

## Launch job from prompt
result = prompt_launch.launch(
    prompt="@ag-plan Review the system architecture",
    provider="codex",
    context="documentation review"
)

## Launch with custom template
result = prompt_launch.launch_with_template(
    template_id="review-default",
    variables={"target": "system-architecture"},
    provider="claude"
)
```

**Prompt Trigger Bridge:**

```python
from audiagentic.execution.jobs import prompt_trigger_bridge

## Process tagged prompt
result = prompt_trigger_bridge.process(
    raw_prompt="@ag-review provider=codex id=job_001 ctx=documentation",
    project_root="."
)

## Normalize prompt
normalized = prompt_trigger_bridge.normalize(
    raw_prompt="@ag-plan Review the code",
    defaults={"provider": "codex", "template": "plan-default"}
)
```

**State Machine:**

```python
from audiagentic.execution.jobs import state_machine

## Transition job state
result = state_machine.transition(
    job_id="job-123",
    new_state="in_progress",
    metadata={"started_by": "agent"}
)

## Validate transition
is_valid = state_machine.validate_transition(
    current_state="ready",
    new_state="in_progress"
)

## Get valid transitions
valid_states = state_machine.get_valid_transitions(current_state="ready")
```

**CLI Operations:**

```bash
## Job control
python -m src.audiagentic.channels.cli.main job-control --operation list
python -m src.audiagentic.channels.cli.main job-control --operation status --job-id job-123

## Prompt launch
python -m src.audiagentic.channels.cli.main prompt-launch --prompt "@ag-plan Review the system"

## Prompt trigger bridge
python -m src.audiagentic.channels.cli.main prompt-trigger-bridge --raw-prompt "@ag-review provider=codex"
```

**Workflow:**
1. Parse incoming prompt with canonical tags
2. Normalize prompt through trigger bridge
3. Create job record with metadata
4. Transition through state machine
5. Execute stages in order
6. Store results and update state
7. Trigger downstream operations (reviews, releases)

## Sync notes
This page should be refreshed when:
- New job operations are added
- Prompt syntax changes
- State machine transitions are modified
- New stages or workflows are introduced

**Sources:**
- `src/audiagentic/execution/jobs/` - Execution implementation
- Prompt syntax configuration in `.audiagentic/prompt-syntax.yaml`
- Job state machine definitions

**Sync frequency:** On execution system changes

## References
- [Runtime System](./system-runtime.md)
- [Planning System](./system-planning.md)
- [Knowledge System](./system-knowledge.md)
- [CLI Tool](../tools/tool-cli.md)
- [AGENTS.md](../../../AGENTS.md) - Canonical prompt tags
