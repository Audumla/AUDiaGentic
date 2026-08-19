#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::path::Path;
use std::sync::Arc;

use audiagentic_application::Application;
use audiagentic_artifact::{ApplicationLock, ArtifactError, ArtifactResolver, resolve_application};
use audiagentic_core::{
    APPLICATION_MANIFEST_SCHEMA_VERSION, ApplicationContext, ApplicationInstanceId,
    ApplicationManifest, ComponentId,
};
use thiserror::Error;

#[derive(Debug, Error)]
pub enum PrepareError {
    #[error("application manifest schema {actual} is unsupported; expected {expected}")]
    UnsupportedManifestSchema { actual: u32, expected: u32 },
    #[error("component id {component} appears more than once in the application manifest")]
    DuplicateComponent { component: ComponentId },
    #[error(transparent)]
    Artifact(#[from] ArtifactError),
}

/// The generic runtime prepares immutable application evidence. It does not
/// construct capabilities, hold a service registry, choose Tokio/Bevy, or expose
/// protocol-specific behavior.
#[derive(Clone, Copy, Debug, Default)]
pub struct Runtime;

impl Runtime {
    pub fn prepare(
        manifest: ApplicationManifest,
        base_dir: impl AsRef<Path>,
        resolver: &impl ArtifactResolver,
    ) -> Result<PreparedApplication, PrepareError> {
        validate_manifest(&manifest)?;
        let lock = resolve_application(&manifest, base_dir, resolver)?;
        Ok(PreparedApplication {
            manifest: Arc::new(manifest),
            lock: Arc::new(lock),
        })
    }
}

#[derive(Clone, Debug)]
pub struct PreparedApplication {
    manifest: Arc<ApplicationManifest>,
    lock: Arc<ApplicationLock>,
}

impl PreparedApplication {
    pub fn manifest(&self) -> &ApplicationManifest {
        self.manifest.as_ref()
    }

    pub fn lock(&self) -> &ApplicationLock {
        self.lock.as_ref()
    }

    /// Let the concrete application construct its own strongly typed state from
    /// the prepared immutable manifest/lock. The runtime never indexes state by
    /// type and never owns capability registration.
    pub fn instantiate<S, E>(
        self,
        instance_id: ApplicationInstanceId,
        factory: impl FnOnce(&ApplicationManifest, &ApplicationLock) -> Result<S, E>,
    ) -> Result<Application<S>, E> {
        let state = factory(self.manifest.as_ref(), self.lock.as_ref())?;
        let context = ApplicationContext::new(self.manifest.id.clone(), instance_id);
        Ok(Application::new(self.manifest, context, state))
    }
}

fn validate_manifest(manifest: &ApplicationManifest) -> Result<(), PrepareError> {
    if manifest.schema_version != APPLICATION_MANIFEST_SCHEMA_VERSION {
        return Err(PrepareError::UnsupportedManifestSchema {
            actual: manifest.schema_version,
            expected: APPLICATION_MANIFEST_SCHEMA_VERSION,
        });
    }

    let mut ids = BTreeSet::new();
    for component in &manifest.components {
        if !ids.insert(component.id.clone()) {
            return Err(PrepareError::DuplicateComponent {
                component: component.id.clone(),
            });
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use audiagentic_artifact::LocalArtifactResolver;
    use audiagentic_core::{ApplicationId, ArtifactRef, ComponentSpec};
    use std::fs;
    use std::path::PathBuf;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn test_dir(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "audiagentic-runtime-{label}-{}-{nonce}",
            std::process::id()
        ))
    }

    #[test]
    fn prepares_lock_then_delegates_typed_state_construction_to_application() {
        let dir = test_dir("prepare");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("component.wasm"), b"demo component").unwrap();

        let mut manifest =
            ApplicationManifest::new(ApplicationId::try_from("demo").unwrap(), "1.0.0");
        manifest.components.push(ComponentSpec::new(
            ComponentId::try_from("greeting").unwrap(),
            ArtifactRef::try_from("file:component.wasm").unwrap(),
        ));

        let prepared = Runtime::prepare(manifest, &dir, &LocalArtifactResolver).unwrap();
        assert_eq!(prepared.lock().components.len(), 1);

        let application = prepared
            .instantiate(
                ApplicationInstanceId::try_from("demo-1").unwrap(),
                |_manifest, lock| Ok::<_, ()>(lock.components[0].digest.to_string()),
            )
            .unwrap();
        assert!(application.state().starts_with("sha256:"));
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn duplicate_component_identity_fails_before_resolution() {
        let mut manifest =
            ApplicationManifest::new(ApplicationId::try_from("demo").unwrap(), "1.0.0");
        let component = ComponentSpec::new(
            ComponentId::try_from("same").unwrap(),
            ArtifactRef::try_from("file:not-needed.wasm").unwrap(),
        );
        manifest.components.push(component.clone());
        manifest.components.push(component);

        assert!(matches!(
            Runtime::prepare(manifest, ".", &LocalArtifactResolver),
            Err(PrepareError::DuplicateComponent { .. })
        ));
    }

    #[test]
    fn unsupported_manifest_schema_fails_before_resolution() {
        let mut manifest =
            ApplicationManifest::new(ApplicationId::try_from("demo").unwrap(), "1.0.0");
        manifest.schema_version += 1;
        assert!(matches!(
            Runtime::prepare(manifest, ".", &LocalArtifactResolver),
            Err(PrepareError::UnsupportedManifestSchema { .. })
        ));
    }
}
