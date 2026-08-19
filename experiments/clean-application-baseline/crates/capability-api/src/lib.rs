use std::fmt;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct WorkflowRequest {
    pub runs: u32,
    pub steps: u16,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowResult {
    pub runs: u32,
    pub completed: u32,
    pub cancelled: u32,
    pub retried: u32,
    pub ticks: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkflowError {
    InvalidRequest(String),
    Unavailable(String),
    Internal(String),
}

impl fmt::Display for WorkflowError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidRequest(detail) => write!(f, "invalid workflow request: {detail}"),
            Self::Unavailable(detail) => write!(f, "workflow unavailable: {detail}"),
            Self::Internal(detail) => write!(f, "workflow failed: {detail}"),
        }
    }
}

impl std::error::Error for WorkflowError {}

#[async_trait]
pub trait Workflow: Send + Sync {
    async fn run(&self, request: WorkflowRequest) -> Result<WorkflowResult, WorkflowError>;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ComponentProbeError {
    Unavailable(String),
    InvalidResponse(String),
    Internal(String),
}

impl fmt::Display for ComponentProbeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Unavailable(detail) => write!(f, "component runtime unavailable: {detail}"),
            Self::InvalidResponse(detail) => write!(
                f,
                "component runtime returned an invalid response: {detail}"
            ),
            Self::Internal(detail) => write!(f, "component runtime failed: {detail}"),
        }
    }
}

impl std::error::Error for ComponentProbeError {}

#[async_trait]
pub trait ComponentProbe: Send + Sync {
    async fn probe(&self) -> Result<String, ComponentProbeError>;
}
