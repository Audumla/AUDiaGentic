#![forbid(unsafe_code)]

use std::collections::BTreeMap;

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use thiserror::Error;

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

#[derive(Clone, Debug, PartialEq)]
pub struct ConfigLayer {
    pub source: ConfigSource,
    pub value: Value,
}

impl ConfigLayer {
    pub fn new(source: ConfigSource, value: Value) -> Self {
        Self { source, value }
    }
}

#[derive(Clone, Debug, Default)]
pub struct ConfigStack {
    layers: Vec<ConfigLayer>,
}

impl ConfigStack {
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a layer with higher precedence than all previously pushed layers.
    pub fn push(mut self, layer: ConfigLayer) -> Self {
        self.layers.push(layer);
        self
    }

    pub fn resolve(&self) -> ResolvedConfig {
        let mut value = Value::Object(Map::new());
        let mut provenance = BTreeMap::new();

        for layer in &self.layers {
            merge_value(
                &mut value,
                &layer.value,
                &layer.source,
                "",
                &mut provenance,
            );
        }

        ResolvedConfig { value, provenance }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct ResolvedConfig {
    value: Value,
    provenance: BTreeMap<String, ConfigSource>,
}

impl ResolvedConfig {
    pub fn value(&self) -> &Value {
        &self.value
    }

    /// Return the winning source for a JSON-pointer leaf path such as `/logging/level`.
    pub fn provenance(&self, pointer: &str) -> Option<&ConfigSource> {
        self.provenance.get(pointer)
    }

    pub fn deserialize<T: DeserializeOwned>(&self) -> Result<T, ConfigError> {
        serde_json::from_value(self.value.clone()).map_err(ConfigError::Deserialize)
    }
}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("resolved configuration could not be deserialized: {0}")]
    Deserialize(serde_json::Error),
}

fn merge_value(
    target: &mut Value,
    incoming: &Value,
    source: &ConfigSource,
    path: &str,
    provenance: &mut BTreeMap<String, ConfigSource>,
) {
    match (target, incoming) {
        (Value::Object(target_map), Value::Object(incoming_map)) => {
            for (key, incoming_value) in incoming_map {
                let child = child_pointer(path, key);
                if let Some(target_value) = target_map.get_mut(key) {
                    merge_value(target_value, incoming_value, source, &child, provenance);
                } else {
                    target_map.insert(key.clone(), incoming_value.clone());
                    record_provenance(incoming_value, source, &child, provenance);
                }
            }
        }
        (target_value, incoming_value) => {
            clear_provenance(path, provenance);
            *target_value = incoming_value.clone();
            record_provenance(incoming_value, source, path, provenance);
        }
    }
}

fn record_provenance(
    value: &Value,
    source: &ConfigSource,
    path: &str,
    provenance: &mut BTreeMap<String, ConfigSource>,
) {
    match value {
        Value::Object(map) if !map.is_empty() => {
            for (key, nested) in map {
                record_provenance(nested, source, &child_pointer(path, key), provenance);
            }
        }
        _ => {
            provenance.insert(pointer_or_root(path), source.clone());
        }
    }
}

fn clear_provenance(path: &str, provenance: &mut BTreeMap<String, ConfigSource>) {
    if path.is_empty() {
        provenance.clear();
        return;
    }
    let prefix = format!("{path}/");
    provenance.retain(|key, _| key != path && !key.starts_with(&prefix));
}

fn child_pointer(parent: &str, key: &str) -> String {
    let escaped = key.replace('~', "~0").replace('/', "~1");
    if parent.is_empty() {
        format!("/{escaped}")
    } else {
        format!("{parent}/{escaped}")
    }
}

fn pointer_or_root(path: &str) -> String {
    if path.is_empty() {
        "/".to_owned()
    } else {
        path.to_owned()
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
        assert_eq!(
            resolved.provenance("/logging/level").unwrap().label,
            "project"
        );
        assert_eq!(
            resolved.provenance("/logging/json").unwrap().label,
            "package"
        );
    }

    #[test]
    fn arrays_are_replaced_and_provenance_follows_the_winner() {
        let resolved = ConfigStack::new()
            .push(ConfigLayer::new(ConfigSource::new("base"), json!({"items": [1, 2]})))
            .push(ConfigLayer::new(ConfigSource::new("user"), json!({"items": [3]})))
            .resolve();

        assert_eq!(resolved.value()["items"], json!([3]));
        assert_eq!(resolved.provenance("/items").unwrap().label, "user");
    }

    #[test]
    fn json_pointer_keys_are_escaped_for_provenance() {
        let resolved = ConfigStack::new()
            .push(ConfigLayer::new(
                ConfigSource::new("one"),
                json!({"a/b": {"x~y": 1}}),
            ))
            .resolve();
        assert_eq!(resolved.provenance("/a~1b/x~0y").unwrap().label, "one");
    }
}
