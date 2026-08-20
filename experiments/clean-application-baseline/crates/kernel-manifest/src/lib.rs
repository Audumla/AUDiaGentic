use std::collections::BTreeMap;

use audiagentic_kernel_core_spike::{ApplicationId, CapabilityId, ComponentId};
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ApplicationManifest {
    pub application: ApplicationId,
    #[serde(default)]
    pub components: BTreeMap<String, ComponentSpec>,
    #[serde(default)]
    pub bindings: Vec<Binding>,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ComponentSpec {
    pub id: ComponentId,
    pub source: String,
    #[serde(default)]
    pub config: Value,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Binding {
    pub capability: CapabilityId,
    pub component: ComponentId,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manifest_selects_components_without_redeclaring_wit_contracts() {
        let manifest = ApplicationManifest {
            application: ApplicationId::new("example.app").unwrap(),
            components: BTreeMap::from([(
                "workflow".into(),
                ComponentSpec {
                    id: ComponentId::new("workflow-bevy").unwrap(),
                    source: "oci://example/workflow:1".into(),
                    config: Value::Null,
                },
            )]),
            bindings: vec![Binding {
                capability: CapabilityId::new("workflow/execute:1").unwrap(),
                component: ComponentId::new("workflow-bevy").unwrap(),
            }],
        };

        assert_eq!(manifest.components.len(), 1);
        assert_eq!(manifest.bindings.len(), 1);
    }
}
