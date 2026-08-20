use async_trait::async_trait;
use serde_json::Value;
use thiserror::Error;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ReconcileOutcome {
    Created,
    Updated,
    Removed,
    Unchanged,
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum ManagedConfigError {
    #[error("managed configuration ownership conflict at `{0}`")]
    Conflict(String),
    #[error("managed configuration format error: `{0}`")]
    Format(String),
    #[error("managed configuration storage error: `{0}`")]
    Storage(String),
}

#[async_trait]
pub trait ManagedConfig: Send + Sync {
    async fn ensure_value(
        &self,
        document: &str,
        key: &str,
        owner: &str,
        value: Value,
    ) -> Result<ReconcileOutcome, ManagedConfigError>;

    async fn remove_owned(
        &self,
        document: &str,
        key: &str,
        owner: &str,
    ) -> Result<ReconcileOutcome, ManagedConfigError>;
}
