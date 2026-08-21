//! Thin, capability-neutral application foundation.
//!
//! This crate deliberately does not know any concrete capability, runtime,
//! transport, component technology, diagnostics system, or I/O framework.

use std::{error::Error, fmt};

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
define_id!(ExecutionId);
define_id!(CorrelationId);

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

/// Correlation identity for one application-owned execution.
///
/// Core carries the values but does not create spans, install tracing
/// subscribers, persist execution state, or define an execution runtime.
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
    fn execution_context_carries_identity_without_runtime_semantics() {
        let context = ExecutionContext::new(
            ExecutionId::new("execution-1").unwrap(),
            CorrelationId::new("correlation-1").unwrap(),
        );
        assert_eq!(context.execution_id().as_str(), "execution-1");
        assert_eq!(context.correlation_id().as_str(), "correlation-1");
    }

    #[test]
    fn identifiers_reject_empty_values() {
        assert!(ExecutionId::new("  ").is_err());
        assert_eq!(CorrelationId::new("corr-1").unwrap().as_str(), "corr-1");
    }
}
