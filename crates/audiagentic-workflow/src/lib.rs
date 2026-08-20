//! Deterministic workflow/state-machine primitives.
//!
//! A workflow definition decides state transitions and emits application-owned
//! effects as data. This crate performs no I/O, process launching, scheduling,
//! retries, persistence, event publication, or global runtime registration.

use std::{error::Error, fmt};

use audiagentic_errors::{CodedError, ErrorCode, ErrorDefinition};

const WORKFLOW_ID_EMPTY: ErrorDefinition = ErrorDefinition::new(
    ErrorCode::new("VAL-WORKFLOW-001"),
    "Workflow instance id must not be empty.",
    "Provide a non-empty workflow instance identifier.",
);
const WORKFLOW_TERMINAL: ErrorDefinition = ErrorDefinition::new(
    ErrorCode::new("CON-WORKFLOW-001"),
    "Workflow is already terminal.",
    "Do not apply new input to a completed or failed workflow instance.",
);
const WORKFLOW_REVISION_CONFLICT: ErrorDefinition = ErrorDefinition::new(
    ErrorCode::new("CON-WORKFLOW-002"),
    "Workflow revision does not match the expected revision.",
    "Reload the current workflow state and retry against its latest revision.",
);
const WORKFLOW_DEFINITION_REJECTED: ErrorDefinition = ErrorDefinition::new(
    ErrorCode::new("CON-WORKFLOW-003"),
    "Workflow definition rejected the transition.",
    "Correct the domain input or state transition according to the owning workflow definition.",
);

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct WorkflowInstanceId(String);

impl WorkflowInstanceId {
    pub fn new(value: impl Into<String>) -> Result<Self, WorkflowIdError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(WorkflowIdError);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkflowIdError;

impl CodedError for WorkflowIdError {
    fn definition(&self) -> &'static ErrorDefinition {
        &WORKFLOW_ID_EMPTY
    }
}

impl fmt::Display for WorkflowIdError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("workflow instance id must not be empty")
    }
}

impl Error for WorkflowIdError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkflowStatus {
    Running,
    Completed,
    Failed,
}

impl WorkflowStatus {
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Completed | Self::Failed)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkflowTransition<S, E> {
    Continue { state: S, effects: Vec<E> },
    Complete { state: S, effects: Vec<E> },
    Fail { state: S, effects: Vec<E> },
}

impl<S, E> WorkflowTransition<S, E> {
    pub fn continuing(state: S, effects: Vec<E>) -> Self {
        Self::Continue { state, effects }
    }

    pub fn complete(state: S, effects: Vec<E>) -> Self {
        Self::Complete { state, effects }
    }

    pub fn fail(state: S, effects: Vec<E>) -> Self {
        Self::Fail { state, effects }
    }
}

/// Domain-owned deterministic workflow logic. Effects are values that an
/// application may interpret through host facilities or other capabilities.
pub trait WorkflowDefinition {
    type State;
    type Input;
    type Effect;
    type Error: Error + Send + Sync + 'static;

    fn decide(
        &self,
        state: &Self::State,
        input: &Self::Input,
    ) -> Result<WorkflowTransition<Self::State, Self::Effect>, Self::Error>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkflowReceipt<E> {
    revision: u64,
    status: WorkflowStatus,
    effects: Vec<E>,
}

impl<E> WorkflowReceipt<E> {
    pub fn revision(&self) -> u64 {
        self.revision
    }

    pub fn status(&self) -> WorkflowStatus {
        self.status
    }

    pub fn effects(&self) -> &[E] {
        &self.effects
    }

    pub fn into_effects(self) -> Vec<E> {
        self.effects
    }
}

#[derive(Debug)]
pub enum WorkflowApplyError<E> {
    Terminal(WorkflowStatus),
    RevisionConflict { expected: u64, actual: u64 },
    Definition(E),
}

impl<E> CodedError for WorkflowApplyError<E> {
    fn definition(&self) -> &'static ErrorDefinition {
        match self {
            Self::Terminal(_) => &WORKFLOW_TERMINAL,
            Self::RevisionConflict { .. } => &WORKFLOW_REVISION_CONFLICT,
            Self::Definition(_) => &WORKFLOW_DEFINITION_REJECTED,
        }
    }
}

impl<E: fmt::Display> fmt::Display for WorkflowApplyError<E> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Terminal(status) => write!(f, "workflow is terminal: {status:?}"),
            Self::RevisionConflict { expected, actual } => write!(
                f,
                "workflow revision conflict: expected {expected}, actual {actual}"
            ),
            Self::Definition(error) => write!(f, "workflow definition error: {error}"),
        }
    }
}

impl<E: Error + 'static> Error for WorkflowApplyError<E> {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Definition(error) => Some(error),
            Self::Terminal(_) | Self::RevisionConflict { .. } => None,
        }
    }
}

/// Serializable-by-the-application workflow state. The crate does not choose a
/// storage format or persistence backend; it only exposes the state required to
/// recover deterministic execution at the same revision.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkflowSnapshot<S> {
    id: WorkflowInstanceId,
    revision: u64,
    status: WorkflowStatus,
    state: S,
}

impl<S> WorkflowSnapshot<S> {
    pub fn new(id: WorkflowInstanceId, revision: u64, status: WorkflowStatus, state: S) -> Self {
        Self {
            id,
            revision,
            status,
            state,
        }
    }

    pub fn id(&self) -> &WorkflowInstanceId {
        &self.id
    }

    pub fn revision(&self) -> u64 {
        self.revision
    }

    pub fn status(&self) -> WorkflowStatus {
        self.status
    }

    pub fn state(&self) -> &S {
        &self.state
    }

    pub fn into_state(self) -> S {
        self.state
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkflowInstance<S> {
    id: WorkflowInstanceId,
    revision: u64,
    status: WorkflowStatus,
    state: S,
}

impl<S> WorkflowInstance<S> {
    pub fn new(id: WorkflowInstanceId, initial_state: S) -> Self {
        Self {
            id,
            revision: 0,
            status: WorkflowStatus::Running,
            state: initial_state,
        }
    }

    pub fn from_snapshot(snapshot: WorkflowSnapshot<S>) -> Self {
        Self {
            id: snapshot.id,
            revision: snapshot.revision,
            status: snapshot.status,
            state: snapshot.state,
        }
    }

    pub fn id(&self) -> &WorkflowInstanceId {
        &self.id
    }

    pub fn revision(&self) -> u64 {
        self.revision
    }

    pub fn status(&self) -> WorkflowStatus {
        self.status
    }

    pub fn state(&self) -> &S {
        &self.state
    }

    pub fn snapshot(&self) -> WorkflowSnapshot<S>
    where
        S: Clone,
    {
        WorkflowSnapshot::new(
            self.id.clone(),
            self.revision,
            self.status,
            self.state.clone(),
        )
    }

    pub fn into_snapshot(self) -> WorkflowSnapshot<S> {
        WorkflowSnapshot::new(self.id, self.revision, self.status, self.state)
    }

    pub fn apply<D>(
        &mut self,
        definition: &D,
        input: &D::Input,
    ) -> Result<WorkflowReceipt<D::Effect>, WorkflowApplyError<D::Error>>
    where
        D: WorkflowDefinition<State = S>,
    {
        self.apply_at(self.revision, definition, input)
    }

    pub fn apply_at<D>(
        &mut self,
        expected_revision: u64,
        definition: &D,
        input: &D::Input,
    ) -> Result<WorkflowReceipt<D::Effect>, WorkflowApplyError<D::Error>>
    where
        D: WorkflowDefinition<State = S>,
    {
        if self.status.is_terminal() {
            return Err(WorkflowApplyError::Terminal(self.status));
        }
        if expected_revision != self.revision {
            return Err(WorkflowApplyError::RevisionConflict {
                expected: expected_revision,
                actual: self.revision,
            });
        }

        let transition = definition
            .decide(&self.state, input)
            .map_err(WorkflowApplyError::Definition)?;
        let (state, status, effects) = match transition {
            WorkflowTransition::Continue { state, effects } => {
                (state, WorkflowStatus::Running, effects)
            }
            WorkflowTransition::Complete { state, effects } => {
                (state, WorkflowStatus::Completed, effects)
            }
            WorkflowTransition::Fail { state, effects } => (state, WorkflowStatus::Failed, effects),
        };

        self.state = state;
        self.status = status;
        self.revision += 1;

        Ok(WorkflowReceipt {
            revision: self.revision,
            status,
            effects,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug, Clone, PartialEq, Eq)]
    enum State {
        Pending,
        Running,
        Done,
    }

    enum Input {
        Start,
        Finish,
    }

    #[derive(Debug, Clone, PartialEq, Eq)]
    enum Effect {
        Launch,
        Record,
    }

    #[derive(Debug)]
    struct DefinitionError;

    impl fmt::Display for DefinitionError {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            f.write_str("invalid transition")
        }
    }

    impl Error for DefinitionError {}

    struct JobWorkflow;

    impl WorkflowDefinition for JobWorkflow {
        type State = State;
        type Input = Input;
        type Effect = Effect;
        type Error = DefinitionError;

        fn decide(
            &self,
            state: &Self::State,
            input: &Self::Input,
        ) -> Result<WorkflowTransition<Self::State, Self::Effect>, Self::Error> {
            match (state, input) {
                (State::Pending, Input::Start) => Ok(WorkflowTransition::continuing(
                    State::Running,
                    vec![Effect::Record, Effect::Launch],
                )),
                (State::Running, Input::Finish) => Ok(WorkflowTransition::complete(
                    State::Done,
                    vec![Effect::Record],
                )),
                _ => Err(DefinitionError),
            }
        }
    }

    #[test]
    fn workflow_is_deterministic_and_effects_are_data() {
        let mut workflow =
            WorkflowInstance::new(WorkflowInstanceId::new("job-1").unwrap(), State::Pending);

        let started = workflow.apply(&JobWorkflow, &Input::Start).unwrap();
        assert_eq!(started.revision(), 1);
        assert_eq!(started.status(), WorkflowStatus::Running);
        assert_eq!(started.effects(), &[Effect::Record, Effect::Launch]);

        let completed = workflow.apply(&JobWorkflow, &Input::Finish).unwrap();
        assert_eq!(completed.status(), WorkflowStatus::Completed);
        assert_eq!(workflow.state(), &State::Done);
        let error = workflow.apply(&JobWorkflow, &Input::Finish).unwrap_err();
        assert_eq!(error.code().as_str(), "CON-WORKFLOW-001");
    }

    #[test]
    fn snapshot_restores_identity_revision_status_and_state() {
        let mut workflow = WorkflowInstance::new(
            WorkflowInstanceId::new("job-restore").unwrap(),
            State::Pending,
        );
        workflow.apply(&JobWorkflow, &Input::Start).unwrap();

        let snapshot = workflow.snapshot();
        let mut restored = WorkflowInstance::from_snapshot(snapshot);
        assert_eq!(restored.id().as_str(), "job-restore");
        assert_eq!(restored.revision(), 1);
        assert_eq!(restored.status(), WorkflowStatus::Running);
        assert_eq!(restored.state(), &State::Running);

        restored.apply(&JobWorkflow, &Input::Finish).unwrap();
        assert_eq!(restored.status(), WorkflowStatus::Completed);
    }

    #[test]
    fn stale_revision_is_rejected_before_domain_logic() {
        let mut workflow =
            WorkflowInstance::new(WorkflowInstanceId::new("job-2").unwrap(), State::Pending);
        let error = workflow
            .apply_at(4, &JobWorkflow, &Input::Start)
            .unwrap_err();
        assert_eq!(error.code().as_str(), "CON-WORKFLOW-002");
        assert!(matches!(
            error,
            WorkflowApplyError::RevisionConflict {
                expected: 4,
                actual: 0
            }
        ));
    }
}
