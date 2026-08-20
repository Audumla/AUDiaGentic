use std::collections::BTreeMap;

use async_trait::async_trait;
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessRequest {
    pub program: String,
    #[serde(default)]
    pub args: Vec<String>,
    #[serde(default)]
    pub environment: BTreeMap<String, String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ProcessOutput {
    pub exit_code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum ProcessError {
    #[error("program is not allowed: `{0}`")]
    Denied(String),
    #[error("process launch failed: `{0}`")]
    Launch(String),
}

#[async_trait]
pub trait ProcessRunner: Send + Sync {
    async fn run(&self, request: ProcessRequest) -> Result<ProcessOutput, ProcessError>;
}
