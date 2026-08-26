use std::{error::Error, io, path::PathBuf};

use audiacore_core::{Application, ApplicationId, CorrelationId};
use audiacore_events::{EventId, EventPolicy, EventSequence, EventStream, EventStreamId};
use audiacore_host::{FileReadAuthority, FileWriteAuthority};
use audiacore_host_native::NativeFileHost;
use audiacore_managed_content::{
    ManagedContentApplyResult, ManagedContentTarget, apply, observe, plan,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BootstrapEvent {
    ContentApplied(ManagedContentApplyResult),
}

pub struct BootstrapState {
    host: NativeFileHost,
    read_authority: FileReadAuthority,
    write_authority: FileWriteAuthority,
    target: ManagedContentTarget,
}

impl BootstrapState {
    fn new(root: PathBuf) -> Result<Self, Box<dyn Error>> {
        Ok(Self {
            host: NativeFileHost,
            read_authority: FileReadAuthority::new(root.clone())?,
            write_authority: FileWriteAuthority::new(root.clone())?,
            target: ManagedContentTarget::new(root.join("bootstrap-state.txt")),
        })
    }

    fn reconcile(&self, desired: &[u8]) -> Result<ManagedContentApplyResult, Box<dyn Error>> {
        let desired = Some(desired.to_vec());
        let observed = observe(&self.host, &self.read_authority, &self.target)?;
        let result = apply(
            &self.host,
            &self.write_authority,
            &plan(&self.target, &observed, &desired),
        )?;
        let verified = observe(&self.host, &self.read_authority, &self.target)?;
        if verified.as_ref() != desired.as_ref() {
            return Err(io::Error::other("bootstrap state verification failed").into());
        }
        Ok(result)
    }
}

pub struct AudiagenticComposition {
    state: BootstrapState,
    events: EventStream<BootstrapEvent>,
}

impl AudiagenticComposition {
    pub fn events(&self) -> &EventStream<BootstrapEvent> {
        &self.events
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct BootstrapRun {
    pub apply_result: ManagedContentApplyResult,
    pub event_sequence: EventSequence,
}

pub fn build_application(root: PathBuf) -> Result<Application<AudiagenticComposition>, Box<dyn Error>> {
    let composition = AudiagenticComposition {
        state: BootstrapState::new(root)?,
        events: EventStream::new(
            EventStreamId::new("audiagentic-bootstrap")?,
            EventPolicy::bounded(32)?,
        ),
    };
    Ok(Application::new(
        ApplicationId::new("audiagentic")?,
        composition,
    ))
}

pub fn run_bootstrap(
    application: &mut Application<AudiagenticComposition>,
    desired: &[u8],
    attempt: u64,
) -> Result<BootstrapRun, Box<dyn Error>> {
    let correlation_id = CorrelationId::new(format!("bootstrap-{attempt}"))?;
    let composition = application.composition_mut();
    let apply_result = composition.state.reconcile(desired)?;
    let event_sequence = composition.events.append(
        EventId::new(format!("bootstrap-content-{attempt}"))?,
        correlation_id,
        None,
        BootstrapEvent::ContentApplied(apply_result),
    )?;

    Ok(BootstrapRun {
        apply_result,
        event_sequence,
    })
}
