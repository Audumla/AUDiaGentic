use std::{
    error::Error,
    fmt, fs,
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    thread,
    time::Duration,
};

use audiagentic_config::{ConfigLayerId, ConfigLayers, ConfigRevision};
use audiagentic_core::{
    Application, ApplicationId, ApplicationIdentity, ApplicationInstanceId, CorrelationId,
    ExecutionContext, ExecutionId,
};
use audiagentic_events::{
    CausationId, EventCursor, EventId, EventPolicy, EventStream, EventStreamError, EventStreamId,
};
use audiagentic_host::{
    FileHost, FileReadAuthority, FileWriteAuthority, ProcessAuthority, ProcessChild, ProcessHost,
    ProcessRequest, ProcessStdio,
};
use audiagentic_host_native::{NativeFileHost, NativeProcessHost};
use audiagentic_managed_config::{
    ConfigApplyResult, ConfigDesired, ManagedConfigTarget, apply as apply_config,
    observe as observe_config, plan as plan_config,
};
use audiagentic_reconcile::{Desired, EffectId, OwnershipId};
use audiagentic_time::{Deadline, TimerId, TimerSet, Timestamp};
use audiagentic_workflow::{
    WorkflowDefinition, WorkflowInstance, WorkflowInstanceId, WorkflowStatus, WorkflowTransition,
};
use schemars::JsonSchema;
use serde::Deserialize;

#[derive(Debug, Deserialize, JsonSchema)]
struct PlatformConfig {
    events: PlatformEventConfig,
}

#[derive(Debug, Deserialize, JsonSchema)]
struct PlatformEventConfig {
    retention: usize,
}

#[derive(Debug, Clone, Copy)]
struct PlatformPolicy {
    events: EventPolicy,
    config_revision: ConfigRevision,
}

fn load_policy() -> Result<PlatformPolicy, Box<dyn Error>> {
    let resolved = ConfigLayers::new()
        .merge_toml(
            ConfigLayerId::new("package-default")?,
            "[events]\nretention = 8\n",
        )
        .merge_toml(ConfigLayerId::new("project")?, "[events]\nretention = 4\n")
        .resolve::<PlatformConfig>()?;

    Ok(PlatformPolicy {
        events: EventPolicy::bounded(resolved.value().events.retention)?,
        config_revision: resolved.revision(),
    })
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum PlatformState {
    Pending,
    Running,
    Done,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum PlatformInput {
    Start,
    ChildObserved,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum PlatformEvent {
    ConfigCreated,
    WorkflowStarted,
    TimerFired,
    ChildRoundTrip(String),
    ConfigReplaced,
    Completed,
    ConfigDeleted,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum PlatformEffect {
    Record(PlatformEvent),
    ArmTimer {
        id: &'static str,
        deadline: Timestamp,
    },
    LaunchChild,
}

#[derive(Debug, Clone, Copy)]
struct PlatformDefinitionError;

impl fmt::Display for PlatformDefinitionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("invalid platform workflow transition")
    }
}

impl Error for PlatformDefinitionError {}

struct PlatformWorkflow;

impl WorkflowDefinition for PlatformWorkflow {
    type State = PlatformState;
    type Input = PlatformInput;
    type Effect = PlatformEffect;
    type Error = PlatformDefinitionError;

    fn decide(
        &self,
        state: &Self::State,
        input: &Self::Input,
    ) -> Result<WorkflowTransition<Self::State, Self::Effect>, Self::Error> {
        match (state, input) {
            (PlatformState::Pending, PlatformInput::Start) => Ok(WorkflowTransition::continuing(
                PlatformState::Running,
                vec![
                    PlatformEffect::Record(PlatformEvent::WorkflowStarted),
                    PlatformEffect::ArmTimer {
                        id: "workflow-deadline",
                        deadline: Timestamp::from_millis(50),
                    },
                    PlatformEffect::LaunchChild,
                ],
            )),
            (PlatformState::Running, PlatformInput::ChildObserved) => {
                Ok(WorkflowTransition::complete(
                    PlatformState::Done,
                    vec![PlatformEffect::Record(PlatformEvent::Completed)],
                ))
            }
            _ => Err(PlatformDefinitionError),
        }
    }
}

struct PlatformComposition {
    file_host: NativeFileHost,
    process_host: NativeProcessHost,
    read_authority: FileReadAuthority,
    write_authority: FileWriteAuthority,
    process_authority: ProcessAuthority,
    policy: PlatformPolicy,
}

fn child_mode() -> Result<(), Box<dyn Error>> {
    let mut line = String::new();
    std::io::stdin().read_line(&mut line)?;
    print!("platform:{}", line);
    std::io::stdout().flush()?;
    thread::sleep(Duration::from_secs(60));
    Ok(())
}

fn next_event_id(counter: &mut u64) -> Result<EventId, Box<dyn Error>> {
    *counter += 1;
    Ok(EventId::new(format!("platform-event-{}", *counter))?)
}

fn record_event(
    stream: &mut EventStream<PlatformEvent>,
    counter: &mut u64,
    correlation: &CorrelationId,
    causation: &CausationId,
    event: PlatformEvent,
) -> Result<(), Box<dyn Error>> {
    stream.append(
        next_event_id(counter)?,
        correlation.clone(),
        Some(causation.clone()),
        event,
    );
    Ok(())
}

fn launch_child(app: &Application<PlatformComposition>) -> Result<String, Box<dyn Error>> {
    let mut child = app.composition().process_host.spawn(
        &app.composition().process_authority,
        ProcessRequest::new(std::env::current_exe()?)
            .arg("--platform-child")
            .inherit_environment(true)
            .stderr(ProcessStdio::Null),
    )?;

    let mut stdin = child
        .take_stdin()
        .ok_or_else(|| std::io::Error::other("child stdin was not piped"))?;
    let stdout = child
        .take_stdout()
        .ok_or_else(|| std::io::Error::other("child stdout was not piped"))?;

    stdin.write_all(b"ping\n")?;
    stdin.flush()?;

    let mut line = String::new();
    let mut reader = BufReader::new(stdout);
    reader.read_line(&mut line)?;
    drop(stdin);

    assert_eq!(line, "platform:ping\n");
    assert!(child.is_running()?);
    child.kill()?;
    let exit = child.wait()?;
    assert!(!exit.success());
    Ok(line.trim().to_owned())
}

fn reconcile_config(
    app: &Application<PlatformComposition>,
    target: &ManagedConfigTarget,
    effect: &str,
    desired: ConfigDesired,
) -> Result<ConfigApplyResult, Box<dyn Error>> {
    let observed = observe_config(
        &app.composition().file_host,
        &app.composition().read_authority,
        target,
    )?;
    let plan = plan_config(target, EffectId::new(effect)?, &observed, &desired);
    let receipt = apply_config(
        &app.composition().file_host,
        &app.composition().write_authority,
        target,
        &plan,
    )?;
    Ok(*receipt.result())
}

fn temp_root() -> PathBuf {
    std::env::temp_dir().join(format!("audiagentic-platform-spike-{}", std::process::id()))
}

fn main() -> Result<(), Box<dyn Error>> {
    if std::env::args().any(|arg| arg == "--platform-child") {
        return child_mode();
    }

    let root = temp_root();
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root)?;

    let policy = load_policy()?;
    assert_eq!(policy.events.retention_limit(), Some(4));
    assert_ne!(policy.config_revision.value(), 0);

    let executable = std::env::current_exe()?;
    let app = Application::new(
        ApplicationIdentity::new(
            ApplicationId::new("application-platform-spike")?,
            ApplicationInstanceId::new("local")?,
        ),
        PlatformComposition {
            file_host: NativeFileHost,
            process_host: NativeProcessHost,
            read_authority: FileReadAuthority::new(&root),
            write_authority: FileWriteAuthority::new(&root),
            process_authority: ProcessAuthority::new([executable]),
            policy,
        },
    );

    let execution = ExecutionContext::new(
        ExecutionId::new("platform-execution-1")?,
        CorrelationId::new("platform-spike")?,
    );
    let causation = CausationId::new("workflow-platform-1")?;

    let target = ManagedConfigTarget::new(
        "application.conf",
        OwnershipId::new("platform-configuration")?,
    );
    assert_eq!(
        reconcile_config(
            &app,
            &target,
            "config-create",
            Desired(Some(b"mode=proof\n".to_vec())),
        )?,
        ConfigApplyResult::Created
    );

    let mut events = EventStream::with_policy(
        EventStreamId::new("platform-1")?,
        app.composition().policy.events,
    );
    let mut event_counter = 0;
    record_event(
        &mut events,
        &mut event_counter,
        execution.correlation_id(),
        &causation,
        PlatformEvent::ConfigCreated,
    )?;

    let mut timers = TimerSet::new();
    let mut workflow = WorkflowInstance::new(
        WorkflowInstanceId::new("platform-workflow-1")?,
        PlatformState::Pending,
    );
    let started = workflow.apply(&PlatformWorkflow, &PlatformInput::Start)?;

    let snapshot = workflow.snapshot();
    workflow = WorkflowInstance::from_snapshot(snapshot);
    assert_eq!(workflow.revision(), 1);
    assert_eq!(workflow.status(), WorkflowStatus::Running);

    for effect in started.into_effects() {
        match effect {
            PlatformEffect::Record(event) => record_event(
                &mut events,
                &mut event_counter,
                execution.correlation_id(),
                &causation,
                event,
            )?,
            PlatformEffect::ArmTimer { id, deadline } => {
                timers.arm(TimerId::new(id)?, Deadline::at(deadline));
            }
            PlatformEffect::LaunchChild => {
                let observed = launch_child(&app)?;
                record_event(
                    &mut events,
                    &mut event_counter,
                    execution.correlation_id(),
                    &causation,
                    PlatformEvent::ChildRoundTrip(observed),
                )?;
            }
        }
    }

    let due = timers.drain_due(Timestamp::from_millis(50));
    assert_eq!(due, vec![TimerId::new("workflow-deadline")?]);
    record_event(
        &mut events,
        &mut event_counter,
        execution.correlation_id(),
        &causation,
        PlatformEvent::TimerFired,
    )?;

    assert_eq!(
        reconcile_config(
            &app,
            &target,
            "config-replace",
            Desired(Some(b"mode=validated\n".to_vec())),
        )?,
        ConfigApplyResult::Replaced
    );
    assert_eq!(
        app.composition()
            .file_host
            .read(&app.composition().read_authority, target.path())?,
        b"mode=validated\n"
    );
    record_event(
        &mut events,
        &mut event_counter,
        execution.correlation_id(),
        &causation,
        PlatformEvent::ConfigReplaced,
    )?;

    let completed = workflow.apply(&PlatformWorkflow, &PlatformInput::ChildObserved)?;
    for effect in completed.into_effects() {
        if let PlatformEffect::Record(event) = effect {
            record_event(
                &mut events,
                &mut event_counter,
                execution.correlation_id(),
                &causation,
                event,
            )?;
        }
    }
    assert_eq!(workflow.status(), WorkflowStatus::Completed);
    assert!(events.iter().any(|event| matches!(
        event.payload(),
        PlatformEvent::ChildRoundTrip(value) if value == "platform:ping"
    )));

    assert!(matches!(
        events.page_after(EventCursor::start(), 2),
        Err(EventStreamError::CursorExpired { .. })
    ));
    let oldest = events
        .oldest_sequence()
        .expect("bounded stream has evidence");
    let first = events.page_after(EventCursor::new(oldest.get() - 1), 2)?;
    assert_eq!(first.events().len(), 2);
    assert!(first.has_more());
    let second = events.page_after(first.next_cursor(), 2)?;
    assert_eq!(second.events().len(), 2);
    assert!(!second.has_more());

    assert_eq!(
        reconcile_config(&app, &target, "config-delete", Desired(None))?,
        ConfigApplyResult::Deleted
    );
    assert_eq!(
        app.composition()
            .file_host
            .read_optional(&app.composition().read_authority, target.path())?,
        None
    );
    record_event(
        &mut events,
        &mut event_counter,
        execution.correlation_id(),
        &causation,
        PlatformEvent::ConfigDeleted,
    )?;

    println!(
        "OBSERVABILITY_SEAM_OK execution={} correlation={} config_revision={}",
        execution.execution_id(),
        execution.correlation_id(),
        app.composition().policy.config_revision
    );
    println!("CONFIG_POLICY_OK");

    fs::remove_dir_all(root)?;
    println!("APPLICATION_PLATFORM_SPIKE_OK");
    Ok(())
}
