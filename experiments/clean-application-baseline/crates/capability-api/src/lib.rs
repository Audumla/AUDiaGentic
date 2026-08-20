use std::{error::Error, fmt, sync::Arc};

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

pub type CapabilityResult<T> = Result<T, CapabilityError>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CapabilityErrorKind {
    Unavailable,
    InvalidRequest,
    Execution,
    Timeout,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CapabilityError {
    kind: CapabilityErrorKind,
    capability: &'static str,
    message: String,
}

impl CapabilityError {
    pub fn unavailable(capability: &'static str) -> Self {
        Self {
            kind: CapabilityErrorKind::Unavailable,
            capability,
            message: "capability is not configured".to_owned(),
        }
    }

    pub fn invalid_request(capability: &'static str, message: impl Into<String>) -> Self {
        Self {
            kind: CapabilityErrorKind::InvalidRequest,
            capability,
            message: message.into(),
        }
    }

    pub fn execution(capability: &'static str, message: impl Into<String>) -> Self {
        Self {
            kind: CapabilityErrorKind::Execution,
            capability,
            message: message.into(),
        }
    }

    pub fn timeout(capability: &'static str, message: impl Into<String>) -> Self {
        Self {
            kind: CapabilityErrorKind::Timeout,
            capability,
            message: message.into(),
        }
    }

    pub fn kind(&self) -> CapabilityErrorKind {
        self.kind
    }

    pub fn capability(&self) -> &'static str {
        self.capability
    }

    pub fn message(&self) -> &str {
        &self.message
    }
}

impl fmt::Display for CapabilityError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.capability, self.message)
    }
}

impl Error for CapabilityError {}

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct WorkflowRequest {
    pub runs: u32,
    pub steps: u16,
}

impl WorkflowRequest {
    pub fn validate(&self) -> CapabilityResult<()> {
        if self.runs == 0 {
            return Err(CapabilityError::invalid_request(
                "workflow",
                "runs must be greater than zero",
            ));
        }
        if self.steps == 0 {
            return Err(CapabilityError::invalid_request(
                "workflow",
                "steps must be greater than zero",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowResult {
    pub runs: u32,
    pub completed: u32,
    pub cancelled: u32,
    pub retried: u32,
    pub ticks: u64,
}

#[async_trait]
pub trait Workflow: Send + Sync {
    async fn run(&self, request: WorkflowRequest) -> CapabilityResult<WorkflowResult>;
}

#[async_trait]
impl<T> Workflow for Arc<T>
where
    T: Workflow + ?Sized,
{
    async fn run(&self, request: WorkflowRequest) -> CapabilityResult<WorkflowResult> {
        (**self).run(request).await
    }
}

#[async_trait]
pub trait ComponentProbe: Send + Sync {
    async fn probe(&self) -> CapabilityResult<String>;
}

#[async_trait]
impl<T> ComponentProbe for Arc<T>
where
    T: ComponentProbe + ?Sized,
{
    async fn probe(&self) -> CapabilityResult<String> {
        (**self).probe().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn workflow_request_rejects_zero_dimensions() {
        let runs = WorkflowRequest { runs: 0, steps: 1 }
            .validate()
            .unwrap_err();
        assert_eq!(runs.kind(), CapabilityErrorKind::InvalidRequest);
        assert_eq!(runs.capability(), "workflow");

        let steps = WorkflowRequest { runs: 1, steps: 0 }
            .validate()
            .unwrap_err();
        assert_eq!(steps.kind(), CapabilityErrorKind::InvalidRequest);
        assert_eq!(steps.capability(), "workflow");
    }

    #[test]
    fn capability_errors_have_stable_categories() {
        let error = CapabilityError::timeout("component_probe", "timed out after 30s");
        assert_eq!(error.kind(), CapabilityErrorKind::Timeout);
        assert_eq!(error.capability(), "component_probe");
        assert!(error.to_string().contains("timed out"));
    }
}
