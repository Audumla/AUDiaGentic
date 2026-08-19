use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ConfigSource(String);

impl ConfigSource {
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ConfigLayer {
    pub source: ConfigSource,
    pub value: Value,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LayeredConfig {
    pub value: Value,
    pub provenance: BTreeMap<String, ConfigSource>,
}

pub fn merge_layers(layers: impl IntoIterator<Item = ConfigLayer>) -> LayeredConfig {
    let mut value = Value::Object(Map::new());
    let mut provenance = BTreeMap::new();

    for layer in layers {
        merge_value(&mut value, layer.value, "", &layer.source, &mut provenance);
    }

    LayeredConfig { value, provenance }
}

fn merge_value(
    target: &mut Value,
    incoming: Value,
    path: &str,
    source: &ConfigSource,
    provenance: &mut BTreeMap<String, ConfigSource>,
) {
    match (target, incoming) {
        (Value::Object(target_map), Value::Object(incoming_map)) => {
            for (key, incoming_value) in incoming_map {
                let child_path = if path.is_empty() {
                    key.clone()
                } else {
                    format!("{path}.{key}")
                };
                match target_map.get_mut(&key) {
                    Some(existing) => {
                        merge_value(existing, incoming_value, &child_path, source, provenance)
                    }
                    None => {
                        record_leaf_provenance(&incoming_value, &child_path, source, provenance);
                        target_map.insert(key, incoming_value);
                    }
                }
            }
        }
        (target_slot, incoming_value) => {
            clear_provenance(path, provenance);
            record_leaf_provenance(&incoming_value, path, source, provenance);
            *target_slot = incoming_value;
        }
    }
}

fn clear_provenance(path: &str, provenance: &mut BTreeMap<String, ConfigSource>) {
    if path.is_empty() {
        provenance.clear();
        return;
    }
    let prefix = format!("{path}.");
    provenance.retain(|existing, _| existing != path && !existing.starts_with(&prefix));
}

fn record_leaf_provenance(
    value: &Value,
    path: &str,
    source: &ConfigSource,
    provenance: &mut BTreeMap<String, ConfigSource>,
) {
    match value {
        Value::Object(map) => {
            for (key, value) in map {
                let child_path = if path.is_empty() {
                    key.clone()
                } else {
                    format!("{path}.{key}")
                };
                record_leaf_provenance(value, &child_path, source, provenance);
            }
        }
        _ if !path.is_empty() => {
            provenance.insert(path.to_owned(), source.clone());
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn later_layers_override_only_their_paths_and_record_provenance() {
        let merged = merge_layers([
            ConfigLayer {
                source: ConfigSource::new("package"),
                value: json!({"runtime": {"threads": 4, "log": "info"}}),
            },
            ConfigLayer {
                source: ConfigSource::new("project"),
                value: json!({"runtime": {"threads": 8}}),
            },
        ]);

        assert_eq!(merged.value["runtime"]["threads"], 8);
        assert_eq!(merged.value["runtime"]["log"], "info");
        assert_eq!(merged.provenance["runtime.threads"].as_str(), "project");
        assert_eq!(merged.provenance["runtime.log"].as_str(), "package");
    }

    #[test]
    fn replacing_a_subtree_clears_stale_provenance() {
        let merged = merge_layers([
            ConfigLayer {
                source: ConfigSource::new("package"),
                value: json!({"runtime": {"threads": 4, "log": "info"}}),
            },
            ConfigLayer {
                source: ConfigSource::new("project"),
                value: json!({"runtime": "disabled"}),
            },
        ]);

        assert_eq!(merged.value["runtime"], "disabled");
        assert_eq!(merged.provenance["runtime"].as_str(), "project");
        assert!(!merged.provenance.contains_key("runtime.threads"));
        assert!(!merged.provenance.contains_key("runtime.log"));
    }
}
