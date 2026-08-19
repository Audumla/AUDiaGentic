#![forbid(unsafe_code)]

use figment::providers::Serialized;
use figment::value::{Dict, Map};
use figment::{Figment, Metadata, Profile, Provider};
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Human-readable identity for a configuration layer.
///
/// The identity is propagated by Figment as per-value metadata, allowing callers
/// to explain where a winning configuration value came from without AUDiaGentic
/// reimplementing merge/provenance machinery.
#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize, Deserialize)]
pub struct ConfigSource {
    pub label: String,
}

impl ConfigSource {
    pub fn new(label: impl Into<String>) -> Self {
        Self {
            label: label.into(),
        }
    }
}

#[derive(Clone, Debug)]
pub struct ConfigLayer {
    source: ConfigSource,
    value: Value,
}

impl ConfigLayer {
    pub fn new(source: ConfigSource, value: Value) -> Self {
        Self { source, value }
    }
}

impl Provider for ConfigLayer {
    fn metadata(&self) -> Metadata {
        Metadata::from(self.source.label.clone(), self.source.label.clone())
    }

    fn data(&self) -> figment::Result<Map<Profile, Dict>> {
        Serialized::defaults(self.value.clone()).data()
    }
}

/// AUDiaGentic's only configuration policy here is ordered precedence: later
/// layers win. Recursive merge behavior, typed extraction, errors and metadata
/// propagation are delegated to Figment.
#[derive(Clone, Debug)]
pub struct ConfigStack {
    figment: Figment,
}

impl Default for ConfigStack {
    fn default() -> Self {
        Self {
            figment: Figment::new(),
        }
    }
}

impl ConfigStack {
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a layer with higher precedence than all previously pushed layers.
    pub fn push(mut self, layer: ConfigLayer) -> Self {
        self.figment = self.figment.merge(layer);
        self
    }

    pub fn resolve(self) -> ResolvedConfig {
        ResolvedConfig {
            figment: self.figment,
        }
    }
}

#[derive(Clone, Debug)]
pub struct ResolvedConfig {
    figment: Figment,
}

impl ResolvedConfig {
    pub fn deserialize<T: DeserializeOwned>(&self) -> figment::Result<T> {
        self.figment.extract()
    }

    pub fn deserialize_inner<T: DeserializeOwned>(&self, key: &str) -> figment::Result<T> {
        self.figment.extract_inner(key)
    }

    /// Return the winning named source for a Figment key path such as
    /// `logging.level`.
    pub fn source(&self, key: &str) -> Option<ConfigSource> {
        self.figment.find_metadata(key).map(|metadata| ConfigSource {
            label: metadata.name.to_string(),
        })
    }

    /// Expose the underlying Figment when an application needs an ecosystem
    /// feature that AUDiaGentic deliberately does not wrap.
    pub fn figment(&self) -> &Figment {
        &self.figment
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;
    use serde_json::json;

    #[derive(Debug, Deserialize, Eq, PartialEq)]
    struct Settings {
        logging: Logging,
        workers: u32,
    }

    #[derive(Debug, Deserialize, Eq, PartialEq)]
    struct Logging {
        level: String,
        json: bool,
    }

    #[test]
    fn later_layers_override_leaves_without_destroying_siblings() {
        let resolved = ConfigStack::new()
            .push(ConfigLayer::new(
                ConfigSource::new("package"),
                json!({"logging": {"level": "info", "json": false}, "workers": 2}),
            ))
            .push(ConfigLayer::new(
                ConfigSource::new("project"),
                json!({"logging": {"level": "debug"}}),
            ))
            .resolve();

        let settings: Settings = resolved.deserialize().unwrap();
        assert_eq!(
            settings,
            Settings {
                logging: Logging {
                    level: "debug".to_owned(),
                    json: false,
                },
                workers: 2,
            }
        );
        assert_eq!(resolved.source("logging.level").unwrap().label, "project");
        assert_eq!(resolved.source("logging.json").unwrap().label, "package");
    }

    #[test]
    fn arrays_are_replaced_by_the_higher_precedence_layer() {
        let resolved = ConfigStack::new()
            .push(ConfigLayer::new(
                ConfigSource::new("base"),
                json!({"items": [1, 2]}),
            ))
            .push(ConfigLayer::new(
                ConfigSource::new("user"),
                json!({"items": [3]}),
            ))
            .resolve();

        let items: Vec<u32> = resolved.deserialize_inner("items").unwrap();
        assert_eq!(items, vec![3]);
        assert_eq!(resolved.source("items").unwrap().label, "user");
    }

    #[test]
    fn extraction_errors_keep_figments_source_metadata() {
        #[derive(Deserialize)]
        struct Invalid {
            workers: u32,
        }

        let resolved = ConfigStack::new()
            .push(ConfigLayer::new(
                ConfigSource::new("project"),
                json!({"workers": "not-a-number"}),
            ))
            .resolve();

        let error = resolved.deserialize::<Invalid>().unwrap_err();
        assert_eq!(error.metadata.as_ref().unwrap().name, "project");
    }
}
