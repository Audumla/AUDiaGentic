use serde::de::DeserializeOwned;
use serde_json::{Map, Value};

#[derive(Clone, Debug, PartialEq)]
pub struct ConfigLayer {
    pub source: String,
    pub value: Value,
}

impl ConfigLayer {
    pub fn new(source: impl Into<String>, value: Value) -> Self {
        Self {
            source: source.into(),
            value,
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct ResolvedConfig {
    pub value: Value,
    pub sources: Vec<String>,
}

pub fn merge_layers(layers: impl IntoIterator<Item = ConfigLayer>) -> ResolvedConfig {
    let mut resolved = Value::Object(Map::new());
    let mut sources = Vec::new();
    for layer in layers {
        merge_value(&mut resolved, layer.value);
        sources.push(layer.source);
    }
    ResolvedConfig {
        value: resolved,
        sources,
    }
}

pub fn deserialize<T: DeserializeOwned>(config: &ResolvedConfig) -> Result<T, serde_json::Error> {
    serde_json::from_value(config.value.clone())
}

fn merge_value(base: &mut Value, overlay: Value) {
    match (base, overlay) {
        (Value::Object(base), Value::Object(overlay)) => {
            for (key, value) in overlay {
                match base.get_mut(&key) {
                    Some(existing) => merge_value(existing, value),
                    None => {
                        base.insert(key, value);
                    }
                }
            }
        }
        (base, overlay) => *base = overlay,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde::Deserialize;
    use serde_json::json;

    #[derive(Debug, Deserialize, PartialEq)]
    struct Example {
        host: String,
        port: u16,
    }

    #[test]
    fn later_layers_override_without_erasing_siblings() {
        let resolved = merge_layers([
            ConfigLayer::new("base", json!({"host":"localhost","port":80})),
            ConfigLayer::new("project", json!({"port":8080})),
        ]);
        assert_eq!(resolved.sources, ["base", "project"]);
        assert_eq!(
            deserialize::<Example>(&resolved).unwrap(),
            Example {
                host: "localhost".into(),
                port: 8080
            }
        );
    }
}
