use std::collections::{BTreeMap, BTreeSet};

use audiagentic_kernel_core_spike::{CapabilityId, ComponentId};
use audiagentic_kernel_manifest_spike::ApplicationManifest;
use thiserror::Error;

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DiscoveredComponent {
    pub id: ComponentId,
    pub exports: BTreeSet<CapabilityId>,
    pub imports: BTreeSet<CapabilityId>,
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum CompositionError {
    #[error("manifest references unknown component `{0}`")]
    UnknownComponent(ComponentId),
    #[error("component `{component}` does not export capability `{capability}`")]
    CapabilityNotExported {
        component: ComponentId,
        capability: CapabilityId,
    },
    #[error("capability `{0}` has no explicit binding")]
    MissingBinding(CapabilityId),
    #[error("capability `{0}` has multiple explicit bindings")]
    DuplicateBinding(CapabilityId),
}

pub fn validate(
    manifest: &ApplicationManifest,
    discovered: &[DiscoveredComponent],
) -> Result<(), CompositionError> {
    let discovered: BTreeMap<_, _> = discovered.iter().map(|c| (c.id.clone(), c)).collect();
    let mut bound = BTreeMap::<CapabilityId, ComponentId>::new();

    for binding in &manifest.bindings {
        if bound
            .insert(binding.capability.clone(), binding.component.clone())
            .is_some()
        {
            return Err(CompositionError::DuplicateBinding(binding.capability.clone()));
        }

        let component = discovered
            .get(&binding.component)
            .ok_or_else(|| CompositionError::UnknownComponent(binding.component.clone()))?;
        if !component.exports.contains(&binding.capability) {
            return Err(CompositionError::CapabilityNotExported {
                component: binding.component.clone(),
                capability: binding.capability.clone(),
            });
        }
    }

    let required: BTreeSet<_> = discovered
        .values()
        .flat_map(|component| component.imports.iter().cloned())
        .collect();
    for capability in required {
        if !bound.contains_key(&capability) {
            return Err(CompositionError::MissingBinding(capability));
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeMap, BTreeSet};

    use audiagentic_kernel_core_spike::{ApplicationId, CapabilityId, ComponentId};
    use audiagentic_kernel_manifest_spike::{ApplicationManifest, Binding, ComponentSpec};
    use serde_json::Value;

    use super::*;

    fn id(value: &str) -> CapabilityId {
        CapabilityId::new(value).unwrap()
    }

    fn component(value: &str) -> ComponentId {
        ComponentId::new(value).unwrap()
    }

    #[test]
    fn explicit_binding_is_validated_against_discovered_exports() {
        let manifest = ApplicationManifest {
            application: ApplicationId::new("app").unwrap(),
            components: BTreeMap::from([(
                "workflow".into(),
                ComponentSpec {
                    id: component("workflow-default"),
                    source: "workflow.wasm".into(),
                    config: Value::Null,
                },
            )]),
            bindings: vec![Binding {
                capability: id("workflow/execute:1"),
                component: component("workflow-default"),
            }],
        };
        let discovered = [DiscoveredComponent {
            id: component("workflow-default"),
            exports: BTreeSet::from([id("workflow/execute:1")]),
            imports: BTreeSet::new(),
        }];
        assert_eq!(validate(&manifest, &discovered), Ok(()));
    }

    #[test]
    fn missing_required_binding_fails_instead_of_guessing() {
        let manifest = ApplicationManifest {
            application: ApplicationId::new("app").unwrap(),
            components: BTreeMap::new(),
            bindings: Vec::new(),
        };
        let discovered = [DiscoveredComponent {
            id: component("consumer"),
            exports: BTreeSet::new(),
            imports: BTreeSet::from([id("storage/read:1")]),
        }];
        assert_eq!(
            validate(&manifest, &discovered),
            Err(CompositionError::MissingBinding(id("storage/read:1")))
        );
    }
}
