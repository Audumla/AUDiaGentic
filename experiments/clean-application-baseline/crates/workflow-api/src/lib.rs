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

#[async_trait]
pub trait Workflow: Send + Sync {
    async fn run(&self, request: WorkflowRequest) -> Result<WorkflowResult, String>;
}
