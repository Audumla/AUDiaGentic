use std::{collections::BTreeSet, fmt};

use serde::{Deserialize, Serialize};

macro_rules! id_type {
    ($name:ident) => {
        #[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            pub fn new(value: impl Into<String>) -> Result<Self, IdentifierError> {
                let value = value.into();
                validate_identifier(&value)?;
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

fn validate_identifier(value: &str) -> Result<(), IdentifierError> {
    if value.is_empty() {
        return Err(IdentifierError::Empty);
    }
    if value.trim() != value || value.chars().any(char::is_control) {
        return Err(IdentifierError::Invalid(value.to_owned()));
    }
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum IdentifierError {
    Empty,
    Invalid(String),
}

impl fmt::Display for IdentifierError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Empty => f.write_str("identifier must not be empty"),
            Self::Invalid(value) => write!(f, "identifier contains invalid whitespace/control characters: {value:?}"),
        }
    }
}

impl std::error::Error for IdentifierError {}

id_type!(ApplicationId);
id_type!(ApplicationInstanceId);
id_type!(ComponentId);
id_type!(CapabilityId);
id_type!(CorrelationId);
id_type!(DiagnosticCode);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Info,
    Warning,
    Error,
    Fatal,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Diagnostic {
    pub code: DiagnosticCode,
    pub severity: Severity,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub help: Option<String>,
}

impl Diagnostic {
    pub fn new(code: DiagnosticCode, severity: Severity, message: impl Into<String>) -> Self {
        Self {
            code,
            severity,
            message: message.into(),
            help: None,
        }
    }

    pub fn with_help(mut self, help: impl Into<String>) -> Self {
        self.help = Some(help.into());
        self
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ApplicationContext {
    pub application: ApplicationId,
    pub instance: ApplicationInstanceId,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub correlation: Option<CorrelationId>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilityRequirement {
    pub capability: CapabilityId,
    #[serde(default)]
    pub optional: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ComponentManifest {
    pub id: ComponentId,
    pub version: String,
    #[serde(default)]
    pub provides: BTreeSet<CapabilityId>,
    #[serde(default)]
    pub requires: Vec<CapabilityRequirement>,
}

impl ComponentManifest {
    pub fn validate(&self) -> Result<(), Diagnostic> {
        if self.version.trim().is_empty() {
            return Err(Diagnostic::new(
                DiagnosticCode::new("CORE-MANIFEST-001").expect("static diagnostic code"),
                Severity::Error,
                format!("component {} has an empty version", self.id),
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ids_reject_empty_or_control_values() {
        assert_eq!(ApplicationId::new(""), Err(IdentifierError::Empty));
        assert!(CapabilityId::new("workflow\nexecute").is_err());
        assert_eq!(
            CapabilityId::new("audiagentic:workflow/engine@1").unwrap().as_str(),
            "audiagentic:workflow/engine@1"
        );
    }

    #[test]
    fn component_manifest_validation_is_domain_neutral() {
        let manifest = ComponentManifest {
            id: ComponentId::new("workflow-bevy").unwrap(),
            version: "1.0.0".into(),
            provides: [CapabilityId::new("workflow.execute").unwrap()].into(),
            requires: vec![],
        };
        assert!(manifest.validate().is_ok());
    }
}
