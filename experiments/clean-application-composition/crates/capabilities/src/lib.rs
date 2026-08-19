use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum CapabilityError {
    #[error("{capability}: {message}")]
    Failed {
        capability: &'static str,
        message: String,
    },
}

impl CapabilityError {
    pub fn failed(capability: &'static str, error: impl std::fmt::Display) -> Self {
        Self::Failed {
            capability,
            message: error.to_string(),
        }
    }
}

pub type CapabilityResult<T> = Result<T, CapabilityError>;

#[async_trait]
pub trait Greeting: Send + Sync {
    async fn greet(&self, name: &str) -> CapabilityResult<String>;
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
pub struct BatchSpec {
    pub runs: u32,
    pub steps: u16,
    pub retry_every: u32,
    pub cancel_every: u32,
}

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct BatchResult {
    pub runs: u32,
    pub completed: u32,
    pub cancelled: u32,
    pub retried: u32,
    pub ticks: u64,
    pub elapsed_micros: u128,
}

#[async_trait]
pub trait Workflow: Send + Sync {
    async fn run_batch(&self, spec: BatchSpec) -> CapabilityResult<BatchResult>;
}
