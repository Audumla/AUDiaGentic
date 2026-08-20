//! Thin, capability-neutral application foundation.
//!
//! This crate deliberately does not know any concrete capability, runtime,
//! transport, component technology, or I/O framework.

use std::{collections::BTreeSet, error::Error, fmt};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IdentifierError {
    kind: &'static str,
}

impl IdentifierError {
    pub fn kind(&self) -> &'static str {
        self.kind
    }
}

impl fmt::Display for IdentifierError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} must not be empty", self.kind)
    }
}

impl Error for IdentifierError {}

macro_rules! define_id {
    ($name:ident) => {
        #[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
        pub struct $name(String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Result<Self, IdentifierError> {
                let value = value.into();
                if value.trim().is_empty() {
                    return Err(IdentifierError {
                        kind: stringify!($name),
                    });
                }
                Ok(Self(value))
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str(&self.0)
            }
        }
    };
}

define_id!(ApplicationId);
define_id!(ApplicationInstanceId);
define_id!(ComponentId);
define_id!(CapabilityId);
define_id!(ExecutionId);
define_id!(CorrelationId);
define_id!(DiagnosticCode);

/// Static component metadata. It describes semantic requirements/exports only;
/// it does not resolve, discover, instantiate, or register implementations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ComponentDescriptor {
    component_id: ComponentId,
    exports: BTreeSet<CapabilityId>,
    requires: BTreeSet<CapabilityId>,
}

impl ComponentDescriptor {
    pub fn new(
        component_id: ComponentId,
        exports: impl IntoIterator<Item = CapabilityId>,
        requires: impl IntoIterator<Item = CapabilityId>,
    ) -> Self {
        Self {
            component_id,
            exports: exports.into_iter().collect(),
            requires: requires.into_iter().collect(),
        }
    }

    pub fn component_id(&self) -> &ComponentId {
        &self.component_id
    }

    pub fn exports(&self) -> &BTreeSet<CapabilityId> {
        &self.exports
    }

    pub fn requires(&self) -> &BTreeSet<CapabilityId> {
        &self.requires
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ApplicationIdentity {
    application_id: ApplicationId,
    instance_id: ApplicationInstanceId,
}

impl ApplicationIdentity {
    pub fn new(application_id: ApplicationId, instance_id: ApplicationInstanceId) -> Self {
        Self {
            application_id,
            instance_id,
        }
    }

    pub fn application_id(&self) -> &ApplicationId {
        &self.application_id
    }

    pub fn instance_id(&self) -> &ApplicationInstanceId {
        &self.instance_id
    }
}

/// An application is identity plus an application-defined, strongly typed
/// composition. Core never interprets, indexes, registers, or erases `C`.
#[derive(Debug, Clone)]
pub struct Application<C> {
    identity: ApplicationIdentity,
    composition: C,
}

impl<C> Application<C> {
    pub fn new(identity: ApplicationIdentity, composition: C) -> Self {
        Self {
            identity,
            composition,
        }
    }

    pub fn identity(&self) -> &ApplicationIdentity {
        &self.identity
    }

    pub fn composition(&self) -> &C {
        &self.composition
    }

    pub fn composition_mut(&mut self) -> &mut C {
        &mut self.composition
    }

    pub fn into_composition(self) -> C {
        self.composition
    }

    pub fn map_composition<N>(self, map: impl FnOnce(C) -> N) -> Application<N> {
        Application {
            identity: self.identity,
            composition: map(self.composition),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutionContext {
    execution_id: ExecutionId,
    correlation_id: CorrelationId,
}

impl ExecutionContext {
    pub fn new(execution_id: ExecutionId, correlation_id: CorrelationId) -> Self {
        Self {
            execution_id,
            correlation_id,
        }
    }

    pub fn execution_id(&self) -> &ExecutionId {
        &self.execution_id
    }

    pub fn correlation_id(&self) -> &CorrelationId {
        &self.correlation_id
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LifecycleState {
    Constructed,
    Starting,
    Running,
    Stopping,
    Stopped,
    Failed,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Lifecycle {
    state: LifecycleState,
}

impl Default for Lifecycle {
    fn default() -> Self {
        Self {
            state: LifecycleState::Constructed,
        }
    }
}

impl Lifecycle {
    pub fn state(&self) -> LifecycleState {
        self.state
    }

    pub fn transition(&mut self, next: LifecycleState) -> Result<(), LifecycleError> {
        if self.state == next || transition_allowed(self.state, next) {
            self.state = next;
            return Ok(());
        }
        Err(LifecycleError {
            from: self.state,
            to: next,
        })
    }
}

fn transition_allowed(from: LifecycleState, to: LifecycleState) -> bool {
    matches!(
        (from, to),
        (LifecycleState::Constructed, LifecycleState::Starting)
            | (LifecycleState::Constructed, LifecycleState::Stopped)
            | (LifecycleState::Starting, LifecycleState::Running)
            | (LifecycleState::Starting, LifecycleState::Failed)
            | (LifecycleState::Running, LifecycleState::Stopping)
            | (LifecycleState::Running, LifecycleState::Failed)
            | (LifecycleState::Stopping, LifecycleState::Stopped)
            | (LifecycleState::Stopping, LifecycleState::Failed)
            | (LifecycleState::Failed, LifecycleState::Stopping)
            | (LifecycleState::Failed, LifecycleState::Stopped)
            | (LifecycleState::Stopped, LifecycleState::Starting)
    )
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LifecycleError {
    from: LifecycleState,
    to: LifecycleState,
}

impl LifecycleError {
    pub fn from(&self) -> LifecycleState {
        self.from
    }

    pub fn to(&self) -> LifecycleState {
        self.to
    }
}

impl fmt::Display for LifecycleError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "invalid lifecycle transition {:?} -> {:?}",
            self.from, self.to
        )
    }
}

impl Error for LifecycleError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DiagnosticSeverity {
    Info,
    Warning,
    Error,
}

/// Machine-readable diagnostic data. Domain errors remain domain-local and
/// may be projected into this form at a boundary; this is not a universal
/// error type.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Diagnostic {
    code: DiagnosticCode,
    severity: DiagnosticSeverity,
    summary: String,
}

impl Diagnostic {
    pub fn new(
        code: DiagnosticCode,
        severity: DiagnosticSeverity,
        summary: impl Into<String>,
    ) -> Self {
        Self {
            code,
            severity,
            summary: summary.into(),
        }
    }

    pub fn code(&self) -> &DiagnosticCode {
        &self.code
    }

    pub fn severity(&self) -> DiagnosticSeverity {
        self.severity
    }

    pub fn summary(&self) -> &str {
        &self.summary
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug, Clone, PartialEq, Eq)]
    struct Calculator;

    #[derive(Debug, Clone, PartialEq, Eq)]
    struct Search;

    fn identity() -> ApplicationIdentity {
        ApplicationIdentity::new(
            ApplicationId::new("test-app").unwrap(),
            ApplicationInstanceId::new("test-1").unwrap(),
        )
    }

    #[test]
    fn application_composition_is_opaque_and_replaceable() {
        let app = Application::new(identity(), Calculator);
        assert_eq!(app.composition(), &Calculator);

        let app = app.map_composition(|_| Search);
        assert_eq!(app.composition(), &Search);
        assert_eq!(app.identity().application_id().as_str(), "test-app");
    }

    #[test]
    fn component_metadata_is_descriptive_not_resolving() {
        let descriptor = ComponentDescriptor::new(
            ComponentId::new("calculator-component").unwrap(),
            [CapabilityId::new("calculator.add").unwrap()],
            [CapabilityId::new("audit.record").unwrap()],
        );
        assert!(
            descriptor
                .exports()
                .contains(&CapabilityId::new("calculator.add").unwrap())
        );
        assert!(
            descriptor
                .requires()
                .contains(&CapabilityId::new("audit.record").unwrap())
        );
    }

    #[test]
    fn lifecycle_enforces_only_generic_lifecycle_semantics() {
        let mut lifecycle = Lifecycle::default();
        lifecycle.transition(LifecycleState::Starting).unwrap();
        lifecycle.transition(LifecycleState::Running).unwrap();
        assert!(lifecycle.transition(LifecycleState::Starting).is_err());
        lifecycle.transition(LifecycleState::Stopping).unwrap();
        lifecycle.transition(LifecycleState::Stopped).unwrap();
    }

    #[test]
    fn identifiers_reject_empty_values() {
        assert!(CapabilityId::new("  ").is_err());
        assert_eq!(
            CapabilityId::new("calc.add").unwrap().as_str(),
            "calc.add"
        );
    }
}
