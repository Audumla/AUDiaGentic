## Summary
The AUDiaGentic runtime system provides lifecycle management, state tracking, and job execution capabilities. It manages the complete lifecycle of workflow jobs from initialization through completion, maintains runtime state for sessions and reviews, and handles installation, migration, and cutover operations.

## Current state
**Runtime System** (`src/audiagentic/runtime/`):

**Lifecycle Management** (`src/audiagentic/runtime/lifecycle/`):
- **Baseline Sync** (`baseline_sync.py`): Establish baseline state for sync operations
- **Checkpoints** (`checkpoints.py`): Create and manage recovery checkpoints
- **Cutover** (`cutover.py`): Manage system cutover operations
- **Detector** (`detector.py`): Detect runtime conditions and state changes
- **Fresh Install** (`fresh_install.py`): Handle fresh installation workflows
- **Manifest** (`manifest.py`): Manage installation manifests
- **Migration** (`migration.py`): Handle data and state migrations
- **Uninstall** (`uninstall.py`): Manage uninstallation and cleanup

**State Management** (`src/audiagentic/runtime/state/`):
- **Jobs Store** (`jobs_store.py`): Persistent storage for job state and history
- **Reviews Store** (`reviews_store.py`): Track review state and outcomes
- **Session Input Store** (`session_input_store.py`): Manage session-specific input state

**Core Capabilities:**
- Lifecycle operations: install, migrate, cutover, uninstall
- State persistence: jobs, reviews, sessions
- Checkpoint management: recovery points for long-running operations
- Event-driven state updates: react to system changes
- Baseline synchronization: establish initial state

**Integration Points:**
- Execution system: jobs trigger lifecycle operations
- Planning system: state changes propagate to knowledge
- Knowledge component: runtime state documented and synced
- Event bus: state changes published as events

## How to use
**Lifecycle Operations:**

```python
from audiagentic.runtime.lifecycle import baseline_sync, checkpoints, migration

## Establish baseline
baseline = baseline_sync.establish_baseline(config)

## Create checkpoint
checkpoint = checkpoints.create_checkpoint(
    operation="job-execution",
    state={"progress": 50, "items_processed": 100}
)

## Restore from checkpoint
restored_state = checkpoints.restore_checkpoint(checkpoint_id)

## Perform migration
migration_result = migration.execute_migration(
    from_version="1.0.0",
    to_version="2.0.0",
    config=config
)
```

**State Management:**

```python
from audiagentic.runtime.state import jobs_store, reviews_store, session_input_store

## Store job state
jobs_store.save_job_state(
    job_id="job-123",
    state="in_progress",
    metadata={"progress": 50}
)

## Retrieve job state
job_state = jobs_store.get_job_state(job_id="job-123")

## Store review state
reviews_store.save_review(
    review_id="review-456",
    item_id="task-0001",
    status="approved",
    feedback="Looks good"
)

## Get review history
reviews = reviews_store.get_reviews_for_item(item_id="task-0001")

## Manage session input
session_input_store.add_input(
    session_id="session-789",
    event_kind="user_prompt",
    details={"prompt": "What should I do next?"}
)

## Get session inputs
inputs = session_input_store.get_session_inputs(session_id="session-789")
```

**CLI Operations:**

```bash
## View job state
python -m src.audiagentic.channels.cli.main job-control --operation status --job-id job-123

## List all jobs
python -m src.audiagentic.channels.cli.main job-control --operation list

## Manage session input
python -m src.audiagentic.channels.cli.main session-input --operation add --details '{"event": "..."}'
```

**Workflow:**
1. Initialize runtime with baseline sync
2. Create checkpoints before long operations
3. Execute jobs with state tracking
4. Store review outcomes
5. Manage session state for context
6. Migrate state when upgrading
7. Cleanup on uninstall

## Sync notes
This page should be refreshed when:
- New lifecycle operations are added
- State store schemas change
- Checkpoint mechanisms are modified
- Migration strategies are updated

**Sources:**
- `src/audiagentic/runtime/lifecycle/` - Lifecycle operations
- `src/audiagentic/runtime/state/` - State management
- Runtime configuration in `.audiagentic/`

**Sync frequency:** On runtime system changes

## References
- [Execution System](./system-execution.md)
- [Planning System](./system-planning.md)
- [Knowledge System](./system-knowledge.md)
- [CLI Tool](../tools/tool-cli.md)
