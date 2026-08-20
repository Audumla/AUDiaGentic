use std::fmt;

use serde::{Deserialize, Serialize};

macro_rules! id_type {
    ($name:ident) => {
        #[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Result<Self, InvalidId> {
                let value = value.into();
                validate_id(&value)?;
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

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InvalidId;

impl fmt::Display for InvalidId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("identifier must be non-empty ASCII [A-Za-z0-9._:/-]")
    }
}

impl std::error::Error for InvalidId {}

fn validate_id(value: &str) -> Result<(), InvalidId> {
    if value.is_empty()
        || !value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b':' | b'/' | b'-'))
    {
        return Err(InvalidId);
    }
    Ok(())
}

id_type!(ApplicationId);
id_type!(ComponentId);
id_type!(CapabilityId);
id_type!(CorrelationId);

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ApplicationContext {
    pub application: ApplicationId,
    pub correlation: Option<CorrelationId>,
}

impl ApplicationContext {
    pub fn new(application: ApplicationId) -> Self {
        Self {
            application,
            correlation: None,
        }
    }

    pub fn with_correlation(mut self, correlation: CorrelationId) -> Self {
        self.correlation = Some(correlation);
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ids_reject_whitespace_and_empty_values() {
        assert!(ApplicationId::new("").is_err());
        assert!(CapabilityId::new("workflow execute").is_err());
        assert_eq!(
            CapabilityId::new("workflow/execute:1").unwrap().as_str(),
            "workflow/execute:1"
        );
    }

    #[test]
    fn context_is_data_not_a_service_locator() {
        let context = ApplicationContext::new(ApplicationId::new("example.app").unwrap())
            .with_correlation(CorrelationId::new("request-42").unwrap());
        assert_eq!(context.application.as_str(), "example.app");
        assert_eq!(context.correlation.unwrap().as_str(), "request-42");
    }
}
