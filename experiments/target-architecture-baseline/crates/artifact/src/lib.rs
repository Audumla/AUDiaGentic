#![forbid(unsafe_code)]

use std::fs;
use std::path::{Path, PathBuf};

use audiagentic_core::{
    ApplicationId, ApplicationManifest, ArtifactDigest, ArtifactRef, ComponentId, ComponentSpec,
};
use serde::{Deserialize, Serialize};
use sha2::{Digest as _, Sha256};
use thiserror::Error;

pub const APPLICATION_LOCK_SCHEMA_VERSION: u32 = 1;

/// Immutable resolution evidence for one component artifact.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct LockedComponent {
    pub id: ComponentId,
    pub artifact: ArtifactRef,
    pub digest: ArtifactDigest,
    pub size_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ApplicationLock {
    pub schema_version: u32,
    pub application_id: ApplicationId,
    pub application_version: String,
    pub components: Vec<LockedComponent>,
}

impl ApplicationLock {
    pub fn new(manifest: &ApplicationManifest, components: Vec<LockedComponent>) -> Self {
        Self {
            schema_version: APPLICATION_LOCK_SCHEMA_VERSION,
            application_id: manifest.id.clone(),
            application_version: manifest.version.clone(),
            components,
        }
    }
}

#[derive(Debug, Error)]
pub enum ArtifactError {
    #[error("artifact reference {reference} is not a local `file:` reference")]
    UnsupportedReference { reference: ArtifactRef },
    #[error("artifact operation failed for {path}: {source}")]
    Io {
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
    #[error(
        "artifact digest mismatch for component {component}: expected {expected}, got {actual}"
    )]
    DigestMismatch {
        component: ComponentId,
        expected: ArtifactDigest,
        actual: ArtifactDigest,
    },
    #[error("generated artifact digest was invalid: {0}")]
    InvalidGeneratedDigest(String),
}

/// Resolve one component artifact into immutable lock evidence.
///
/// Resolution technology is deliberately outside the application model. A
/// local file resolver, OCI resolver, test resolver, or application-specific
/// resolver can all produce the same `LockedComponent` evidence.
pub trait ArtifactResolver {
    fn resolve(
        &self,
        component: &ComponentSpec,
        base_dir: &Path,
    ) -> Result<LockedComponent, ArtifactError>;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct LocalArtifactResolver;

impl ArtifactResolver for LocalArtifactResolver {
    fn resolve(
        &self,
        component: &ComponentSpec,
        base_dir: &Path,
    ) -> Result<LockedComponent, ArtifactError> {
        resolve_local_component(component, base_dir)
    }
}

pub fn resolve_application(
    manifest: &ApplicationManifest,
    base_dir: impl AsRef<Path>,
    resolver: &impl ArtifactResolver,
) -> Result<ApplicationLock, ArtifactError> {
    let base_dir = base_dir.as_ref();
    let mut locked = Vec::with_capacity(manifest.components.len());
    for component in &manifest.components {
        locked.push(resolver.resolve(component, base_dir)?);
    }
    Ok(ApplicationLock::new(manifest, locked))
}

pub fn resolve_local_application(
    manifest: &ApplicationManifest,
    base_dir: impl AsRef<Path>,
) -> Result<ApplicationLock, ArtifactError> {
    resolve_application(manifest, base_dir, &LocalArtifactResolver)
}

pub fn resolve_local_component(
    component: &ComponentSpec,
    base_dir: impl AsRef<Path>,
) -> Result<LockedComponent, ArtifactError> {
    let reference = component.artifact.as_str();
    let Some(relative) = reference.strip_prefix("file:") else {
        return Err(ArtifactError::UnsupportedReference {
            reference: component.artifact.clone(),
        });
    };
    let raw_path = Path::new(relative);
    let path = if raw_path.is_absolute() {
        raw_path.to_owned()
    } else {
        base_dir.as_ref().join(raw_path)
    };
    let bytes = fs::read(&path).map_err(|source| ArtifactError::Io {
        path: path.clone(),
        source,
    })?;
    let actual = sha256_digest(&bytes)?;
    if let Some(expected) = &component.digest
        && expected != &actual
    {
        return Err(ArtifactError::DigestMismatch {
            component: component.id.clone(),
            expected: expected.clone(),
            actual,
        });
    }

    Ok(LockedComponent {
        id: component.id.clone(),
        artifact: component.artifact.clone(),
        digest: actual,
        size_bytes: bytes.len() as u64,
    })
}

pub fn sha256_digest(bytes: &[u8]) -> Result<ArtifactDigest, ArtifactError> {
    let digest = Sha256::digest(bytes);
    let mut encoded = String::with_capacity(7 + digest.len() * 2);
    encoded.push_str("sha256:");
    for byte in digest {
        use std::fmt::Write as _;
        write!(&mut encoded, "{byte:02x}").expect("writing to String cannot fail");
    }
    ArtifactDigest::try_from(encoded)
        .map_err(|error| ArtifactError::InvalidGeneratedDigest(error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use audiagentic_core::{ApplicationId, ArtifactRef, ComponentId};
    use std::time::{SystemTime, UNIX_EPOCH};

    fn test_dir(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "audiagentic-artifact-{label}-{}-{nonce}",
            std::process::id()
        ))
    }

    #[test]
    fn local_resolution_produces_stable_lock_and_enforces_declared_digest() {
        let dir = test_dir("lock");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("component.wasm"), b"component bytes").unwrap();

        let mut manifest =
            ApplicationManifest::new(ApplicationId::try_from("demo").unwrap(), "1.0.0");
        let mut spec = ComponentSpec::new(
            ComponentId::try_from("example").unwrap(),
            ArtifactRef::try_from("file:component.wasm").unwrap(),
        );
        let expected = sha256_digest(b"component bytes").unwrap();
        spec.digest = Some(expected.clone());
        manifest.components.push(spec);

        let lock = resolve_local_application(&manifest, &dir).unwrap();
        assert_eq!(lock.application_id, manifest.id);
        assert_eq!(lock.components.len(), 1);
        assert_eq!(lock.components[0].digest, expected);
        assert_eq!(lock.components[0].size_bytes, 15);

        fs::write(dir.join("component.wasm"), b"tampered").unwrap();
        assert!(matches!(
            resolve_local_application(&manifest, &dir),
            Err(ArtifactError::DigestMismatch { .. })
        ));
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn unsupported_schemes_fail_instead_of_being_guessed() {
        let component = ComponentSpec::new(
            ComponentId::try_from("remote").unwrap(),
            ArtifactRef::try_from("oci://example/component:1").unwrap(),
        );
        assert!(matches!(
            resolve_local_component(&component, "."),
            Err(ArtifactError::UnsupportedReference { .. })
        ));
    }
}
