#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::fmt;
use std::str::FromStr;

use serde::de::Error as _;
use serde::{Deserialize, Deserializer, Serialize};
use serde_json::Value;
use thiserror::Error;

pub const APPLICATION_MANIFEST_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Eq, PartialEq, Error)]
pub enum IdentityError {
    #[error("{kind} must not be empty")]
    Empty { kind: &'static str },
    #[error("{kind} must not contain leading or trailing whitespace")]
    SurroundingWhitespace { kind: &'static str },
}

fn validate_identity(raw: &str, kind: &'static str) -> Result<(), IdentityError> {
    if raw.is_empty() {
        return Err(IdentityError::Empty { kind });
    }
    if raw.trim() != raw {
        return Err(IdentityError::SurroundingWhitespace { kind });
    }
    Ok(())
}

macro_rules! string_id {
    ($name:ident, $kind:literal) => {
        #[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Hash, Serialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl TryFrom<String> for $name {
            type Error = IdentityError;

            fn try_from(value: String) -> Result<Self, Self::Error> {
                validate_identity(&value, $kind)?;
                Ok(Self(value))
            }
        }

        impl TryFrom<&str> for $name {
            type Error = IdentityError;

            fn try_from(value: &str) -> Result<Self, Self::Error> {
                Self::try_from(value.to_owned())
            }
        }

        impl FromStr for $name {
            type Err = IdentityError;

            fn from_str(value: &str) -> Result<Self, Self::Err> {
                Self::try_from(value)
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                formatter.write_str(&self.0)
            }
        }

        impl From<$name> for String {
            fn from(value: $name) -> Self {
                value.0
            }
        }

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
            where
                D: Deserializer<'de>,
            {
                let value = String::deserialize(deserializer)?;
                Self::try_from(value).map_err(D::Error::custom)
            }
        }
    };
}

string_id!(ApplicationId, "application id");
string_id!(ApplicationInstanceId, "application instance id");
string_id!(ComponentId, "component id");
string_id!(CapabilityId, "capability id");
string_id!(ArtifactRef, "artifact reference");
string_id!(ArtifactDigest, "artifact digest");
string_id!(CorrelationId, "correlation id");
string_id!(DiagnosticCode, "diagnostic code");

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ComponentSpec {
    pub id: ComponentId,
    pub artifact: ArtifactRef,
    #[serde(default)]
    pub digest: Option<ArtifactDigest>,
    #[serde(default)]
    pub config: BTreeMap<String, Value>,
}

impl ComponentSpec {
    pub fn new(id: ComponentId, artifact: ArtifactRef) -> Self {
        Self {
            id,
            artifact,
            digest: None,
            config: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ApplicationManifest {
    pub schema_version: u32,
    pub id: ApplicationId,
    pub version: String,
    #[serde(default)]
    pub components: Vec<ComponentSpec>,
    #[serde(default)]
    pub metadata: BTreeMap<String, String>,
}

impl ApplicationManifest {
    pub fn new(id: ApplicationId, version: impl Into<String>) -> Self {
        Self {
            schema_version: APPLICATION_MANIFEST_SCHEMA_VERSION,
            id,
            version: version.into(),
            components: Vec::new(),
            metadata: BTreeMap::new(),
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Trace,
    Info,
    Warning,
    Error,
    Fatal,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct Diagnostic {
    pub code: DiagnosticCode,
    pub severity: Severity,
    pub summary: String,
    #[serde(default)]
    pub detail: Option<String>,
    #[serde(default)]
    pub help: Option<String>,
}

impl Diagnostic {
    pub fn new(code: DiagnosticCode, severity: Severity, summary: impl Into<String>) -> Self {
        Self {
            code,
            severity,
            summary: summary.into(),
            detail: None,
            help: None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ApplicationContext {
    pub application_id: ApplicationId,
    pub instance_id: ApplicationInstanceId,
    #[serde(default)]
    pub correlation_id: Option<CorrelationId>,
}

impl ApplicationContext {
    pub fn new(application_id: ApplicationId, instance_id: ApplicationInstanceId) -> Self {
        Self {
            application_id,
            instance_id,
            correlation_id: None,
        }
    }

    pub fn with_correlation(mut self, correlation_id: CorrelationId) -> Self {
        self.correlation_id = Some(correlation_id);
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn identifiers_reject_blank_and_surrounding_whitespace() {
        assert!(ApplicationId::try_from("").is_err());
        assert!(ApplicationId::try_from(" demo").is_err());
        assert!(ApplicationId::try_from("demo ").is_err());
        assert_eq!(ApplicationId::try_from("demo").unwrap().as_str(), "demo");
    }

    #[test]
    fn identifier_validation_survives_deserialization() {
        let error = serde_json::from_str::<ApplicationId>(r#"" bad ""#).unwrap_err();
        assert!(error.to_string().contains("whitespace"));
    }

    #[test]
    fn manifest_round_trips_without_runtime_types() {
        let mut manifest =
            ApplicationManifest::new(ApplicationId::try_from("demo.app").unwrap(), "1.0.0");
        manifest.components.push(ComponentSpec::new(
            ComponentId::try_from("search").unwrap(),
            ArtifactRef::try_from("oci://example/search:1").unwrap(),
        ));

        let encoded = serde_json::to_string(&manifest).unwrap();
        let decoded: ApplicationManifest = serde_json::from_str(&encoded).unwrap();
        assert_eq!(decoded, manifest);
    }

    #[test]
    fn diagnostics_keep_machine_identity_separate_from_text() {
        let diagnostic = Diagnostic::new(
            DiagnosticCode::try_from("CFG-001").unwrap(),
            Severity::Error,
            "configuration is invalid",
        );
        assert_eq!(diagnostic.code.as_str(), "CFG-001");
        assert_eq!(diagnostic.summary, "configuration is invalid");
    }
}
