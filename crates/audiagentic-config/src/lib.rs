//! Typed configuration extraction and in-memory layer resolution.
//!
//! Configuration models remain application-owned Rust types. This crate does
//! not read files, inspect environment variables, discover projects, or expose a
//! service registry. Applications load raw sources at their composition edge,
//! resolve precedence here, then translate the resolved model into narrow
//! capability-owned policy values.

use std::fmt;

use audiagentic_errors::{CodedError, ErrorCode, ErrorDefinition};
use figment::{
    Figment,
    providers::{Format, Toml},
};
pub use schemars::JsonSchema;
use serde::de::DeserializeOwned;
use thiserror::Error;

const EMPTY_LAYER_ID: ErrorDefinition = ErrorDefinition::new(
    ErrorCode::new("VAL-CONFIG-001"),
    "Configuration layer id must not be empty.",
    "Provide a stable non-empty name for each configuration layer.",
);
const EXTRACTION_FAILED: ErrorDefinition = ErrorDefinition::new(
    ErrorCode::new("CFG-CONFIG-001"),
    "Configuration extraction failed.",
    "Correct the effective configuration so it matches the application-owned schema.",
);

const FNV_OFFSET_BASIS: u64 = 0xcbf29ce484222325;
const FNV_PRIME: u64 = 0x100000001b3;

pub trait ConfigModel: DeserializeOwned + JsonSchema {}

impl<T> ConfigModel for T where T: DeserializeOwned + JsonSchema {}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("configuration layer id must not be empty")]
    EmptyLayerId,
    #[error("configuration extraction failed: {0}")]
    Extract(#[source] Box<figment::Error>),
}

impl CodedError for ConfigError {
    fn definition(&self) -> &'static ErrorDefinition {
        match self {
            Self::EmptyLayerId => &EMPTY_LAYER_ID,
            Self::Extract(_) => &EXTRACTION_FAILED,
        }
    }
}

impl From<figment::Error> for ConfigError {
    fn from(error: figment::Error) -> Self {
        Self::Extract(Box::new(error))
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ConfigLayerId(String);

impl ConfigLayerId {
    pub fn new(value: impl Into<String>) -> Result<Self, ConfigError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(ConfigError::EmptyLayerId);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for ConfigLayerId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// Deterministic identity for the exact ordered raw configuration sources used
/// to resolve a model. It is provenance, not a cryptographic content digest and
/// not a promise that semantically equivalent source text has the same value.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct ConfigRevision(u64);

impl ConfigRevision {
    pub const fn value(self) -> u64 {
        self.0
    }
}

impl fmt::Display for ConfigRevision {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:016x}", self.0)
    }
}

#[derive(Debug)]
pub struct ResolvedConfig<T> {
    value: T,
    revision: ConfigRevision,
    layers: Vec<ConfigLayerId>,
}

impl<T> ResolvedConfig<T> {
    pub fn value(&self) -> &T {
        &self.value
    }

    pub const fn revision(&self) -> ConfigRevision {
        self.revision
    }

    pub fn layers(&self) -> &[ConfigLayerId] {
        &self.layers
    }
}

/// Ordered in-memory configuration composition. Later TOML layers override
/// earlier layers through Figment. Source acquisition remains outside this
/// crate so filesystem/environment authority cannot leak into semantic config.
///
/// Resolution always returns provenance with the typed value. There is no
/// convenience extraction path that silently discards layer identity/revision.
pub struct ConfigLayers {
    figment: Figment,
    revision_state: u64,
    layers: Vec<ConfigLayerId>,
}

impl ConfigLayers {
    pub fn new() -> Self {
        Self {
            figment: Figment::new(),
            revision_state: FNV_OFFSET_BASIS,
            layers: Vec::new(),
        }
    }

    pub fn merge_toml(mut self, id: ConfigLayerId, source: &str) -> Self {
        self.revision_state = hash_bytes(self.revision_state, id.as_str().as_bytes());
        self.revision_state = hash_bytes(self.revision_state, &[0]);
        self.revision_state = hash_bytes(self.revision_state, source.as_bytes());
        self.revision_state = hash_bytes(self.revision_state, &[0xff]);
        self.figment = self.figment.merge(Toml::string(source));
        self.layers.push(id);
        self
    }

    pub fn resolve<T: ConfigModel>(self) -> Result<ResolvedConfig<T>, ConfigError> {
        let value = self.figment.extract::<T>().map_err(ConfigError::from)?;
        Ok(ResolvedConfig {
            value,
            revision: ConfigRevision(self.revision_state),
            layers: self.layers,
        })
    }
}

impl Default for ConfigLayers {
    fn default() -> Self {
        Self::new()
    }
}

fn hash_bytes(mut state: u64, bytes: &[u8]) -> u64 {
    for byte in bytes {
        state ^= u64::from(*byte);
        state = state.wrapping_mul(FNV_PRIME);
    }
    state
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;

    #[derive(Debug, Deserialize, JsonSchema, PartialEq, Eq)]
    struct TestConfig {
        name: String,
        count: u16,
    }

    fn resolve(source: &str) -> Result<ResolvedConfig<TestConfig>, ConfigError> {
        ConfigLayers::new()
            .merge_toml(ConfigLayerId::new("test")?, source)
            .resolve()
    }

    #[test]
    fn extracts_typed_toml_with_provenance() {
        let resolved = resolve("name = 'demo'\ncount = 3\n").unwrap();
        assert_eq!(resolved.value().name, "demo");
        assert_eq!(resolved.value().count, 3);
        assert_eq!(resolved.layers()[0].as_str(), "test");
        assert_ne!(resolved.revision().value(), 0);
    }

    #[test]
    fn ordered_layers_override_without_reading_external_sources() {
        let resolved: ResolvedConfig<TestConfig> = ConfigLayers::new()
            .merge_toml(
                ConfigLayerId::new("package-default").unwrap(),
                "name = 'base'\ncount = 1\n",
            )
            .merge_toml(
                ConfigLayerId::new("project").unwrap(),
                "name = 'project'\ncount = 7\n",
            )
            .resolve()
            .unwrap();

        assert_eq!(resolved.value().name, "project");
        assert_eq!(resolved.value().count, 7);
        assert_eq!(resolved.layers()[0].as_str(), "package-default");
        assert_eq!(resolved.layers()[1].as_str(), "project");
        assert_ne!(resolved.revision().value(), 0);
    }

    #[test]
    fn config_revision_changes_when_a_source_changes() {
        fn revision(source: &str) -> ConfigRevision {
            resolve(source).unwrap().revision()
        }

        assert_ne!(
            revision("name = 'demo'\ncount = 1\n"),
            revision("name = 'demo'\ncount = 2\n")
        );
    }

    #[test]
    fn invalid_configuration_is_a_coded_local_error() {
        let error = resolve("name = 42\ncount = 3\n").unwrap_err();
        assert_eq!(error.code().as_str(), "CFG-CONFIG-001");
        assert_eq!(
            error.canonical_message(),
            "Configuration extraction failed."
        );
    }
}
