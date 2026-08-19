#![forbid(unsafe_code)]

use thiserror::Error;

#[derive(Clone, Debug, Eq, PartialEq, Error)]
#[error("greeting capability failed: {message}")]
pub struct GreetingError {
    message: String,
}

impl GreetingError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

/// Example of a capability contract living outside AUDiaGentic core.
pub trait Greeting: Send + Sync {
    fn greet(&self, name: &str) -> Result<String, GreetingError>;
}
