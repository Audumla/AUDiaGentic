use async_trait::async_trait;
use audiagentic_foundation_sensitive_spike::Secret;
use thiserror::Error;

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SecretRef(String);

impl SecretRef {
    pub fn new(value: impl Into<String>) -> Result<Self, SecretError> {
        let value = value.into();
        if value.is_empty() || value.chars().any(char::is_whitespace) {
            return Err(SecretError::InvalidReference(value));
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, Error, PartialEq, Eq)]
pub enum SecretError {
    #[error("invalid secret reference `{0}`")]
    InvalidReference(String),
    #[error("secret not found: `{0}`")]
    NotFound(String),
    #[error("secret access denied: `{0}`")]
    Denied(String),
    #[error("secret backend failed: `{0}`")]
    Backend(String),
}

#[async_trait]
pub trait SecretStore: Send + Sync {
    async fn resolve(&self, reference: &SecretRef) -> Result<Secret<String>, SecretError>;
}
