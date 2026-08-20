use std::{
    error::Error,
    fmt,
    io::{BufRead, BufReader, Write},
    path::PathBuf,
    thread,
    time::Duration,
};

use audiagentic_core::CorrelationId;
use audiagentic_events::{CausationId, EventId, EventStream, EventStreamId};
use audiagentic_host::{ProcessAuthority, ProcessChild, ProcessHost, ProcessRequest};
use audiagentic_host_native::NativeProcessHost;
use audiagentic_workflow::{
    WorkflowDefinition, WorkflowInstance, WorkflowInstanceId, WorkflowStatus, WorkflowTransition,
};

#[derive(Debug, Clone, PartialEq, Eq)]
enum JobState {
    Pending,
    Running,
    Done,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum JobInput {
    Start,
    ChildObserved,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum JobEvent {
    Started,
    ChildRoundTrip(String),
    Completed,
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum JobEffect {
    Record(JobEvent),
    LaunchChild,
}

#[derive(Debug, Clone, Copy)]
struct JobDefinitionError;

impl fmt::Display for JobDefinitionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("invalid job workflow transition")
    }
}

impl Error for JobDefinitionError {}

struct JobWorkflow;

impl WorkflowDefinition for JobWorkflow {
    type State = JobState;
    type Input = JobInput;
    type Effect = JobEffect;
    type Error = JobDefinitionError;

    fn decide(
        &self,
        state: &Self::State,
        input: &Self::Input,
    ) -> Result<WorkflowTransition<Self::State, Self::Effect>, Self::Error> {
        match (state, input) {
            (JobState::Pending, JobInput::Start) => Ok(WorkflowTransition::continuing(
                JobState::Running,
                vec![
                    JobEffect::Record(JobEvent::Started),
                    JobEffect::LaunchChild,
                ],
            )),
            (JobState::Running, JobInput::ChildObserved) => Ok(WorkflowTransition::complete(
                JobState::Done,
                vec![JobEffect::Record(JobEvent::Completed)],
            )),
            _ => Err(JobDefinitionError),
        }
    }
}

fn child_mode() -> Result<(), Box<dyn Error>> {
    let mut line = String::new();
    std::io::stdin().read_line(&mut line)?;
    print!("echo:{}", line);
    std::io::stdout().flush()?;
    thread::sleep(Duration::from_secs(60));
    Ok(())
}

fn next_event_id(counter: &mut u64) -> Result<EventId, Box<dyn Error>> {
    *counter += 1;
    Ok(EventId::new(format!("event-{}", *counter))?)
}

fn record_event(
    stream: &mut EventStream<JobEvent>,
    counter: &mut u64,
    correlation: &CorrelationId,
    causation: &CausationId,
    event: JobEvent,
) -> Result<(), Box<dyn Error>> {
    stream.append(
        next_event_id(counter)?,
        correlation.clone(),
        Some(causation.clone()),
        event,
    );
    Ok(())
}

fn launch_child(program: PathBuf) -> Result<String, Box<dyn Error>> {
    let authority = ProcessAuthority::new([program.clone()]);
    let mut child = NativeProcessHost.spawn(
        &authority,
        ProcessRequest::new(program).arg("--capability-child"),
    )?;

    {
        let stdin = child.stdin().ok_or_else(|| std::io::Error::other("child stdin was not piped"))?;
        stdin.write_all(b"ping\n")?;
        stdin.flush()?;
    }

    let mut line = String::new();
    {
        let stdout = child.stdout().ok_or_else(|| std::io::Error::other("child stdout was not piped"))?;
        let mut reader = BufReader::new(stdout);
        reader.read_line(&mut line)?;
    }

    assert_eq!(line, "echo:ping\n");
    assert!(child.try_wait()?.is_none());
    child.kill()?;
    let exit = child.wait()?;
    assert!(!exit.success());
    Ok(line.trim().to_owned())
}

fn main() -> Result<(), Box<dyn Error>> {
    if std::env::args().any(|arg| arg == "--capability-child") {
        return child_mode();
    }

    let correlation = CorrelationId::new("capability-proof")?;
    let causation = CausationId::new("workflow-job-1")?;
    let mut events = EventStream::new(EventStreamId::new("job-1")?);
    let mut event_counter = 0;
    let mut workflow = WorkflowInstance::new(
        WorkflowInstanceId::new("job-1")?,
        JobState::Pending,
    );

    let started = workflow.apply(&JobWorkflow, &JobInput::Start)?;
    for effect in started.into_effects() {
        match effect {
            JobEffect::Record(event) => record_event(
                &mut events,
                &mut event_counter,
                &correlation,
                &causation,
                event,
            )?,
            JobEffect::LaunchChild => {
                let observed = launch_child(std::env::current_exe()?)?;
                record_event(
                    &mut events,
                    &mut event_counter,
                    &correlation,
                    &causation,
                    JobEvent::ChildRoundTrip(observed),
                )?;
            }
        }
    }

    let completed = workflow.apply(&JobWorkflow, &JobInput::ChildObserved)?;
    for effect in completed.into_effects() {
        if let JobEffect::Record(event) = effect {
            record_event(
                &mut events,
                &mut event_counter,
                &correlation,
                &causation,
                event,
            )?;
        }
    }

    assert_eq!(workflow.status(), WorkflowStatus::Completed);
    assert_eq!(workflow.revision(), 2);
    assert_eq!(events.len(), 3);
    assert!(matches!(
        events.iter().nth(1).unwrap().payload(),
        JobEvent::ChildRoundTrip(value) if value == "echo:ping"
    ));

    println!("APPLICATION_CAPABILITIES_OK");
    Ok(())
}
