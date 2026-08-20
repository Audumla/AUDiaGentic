//! Typed configuration extraction. Configuration models remain application-
//! owned Rust types; there is no module-string/object loader or service registry.

use figment::{
    Figment,
    providers::{Format, Toml},
};
pub use schemars::JsonSchema;
use serde::de::DeserializeOwned;
use thiserror::Error;

pub trait ConfigModel: DeserializeOwned + JsonSchema {}

impl<T> ConfigModel for T where T: DeserializeOwned + JsonSchema {}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("configuration extraction failed: {0}")]
    Extract(#[source] Box<figment::Error>),
}

impl From<figment::Error> for ConfigError {
    fn from(error: figment::Error) -> Self {
        Self::Extract(Box::new(error))
    }
}

pub fn from_toml<T: ConfigModel>(source: &str) -> Result<T, ConfigError> {
    from_figment(Figment::new().merge(Toml::string(source)))
}

pub fn from_figment<T: ConfigModel>(figment: Figment) -> Result<T, ConfigError> {
    figment.extract::<T>().map_err(ConfigError::from)
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

    #[test]
    fn extracts_typed_toml() {
        let config: TestConfig = from_toml("name = 'demo'\ncount = 3\n").unwrap();
        assert_eq!(config.name, "demo");
        assert_eq!(config.count, 3);
    }

    #[test]
    fn invalid_configuration_is_a_local_typed_error() {
        let error = from_toml::<TestConfig>("name = 42\ncount = 3\n").unwrap_err();
        assert!(
            error
                .to_string()
                .contains("configuration extraction failed")
        );
    }
}
