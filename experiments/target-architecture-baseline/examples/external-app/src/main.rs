#![forbid(unsafe_code)]

use std::convert::Infallible;
use std::path::Path;

use audiagentic_artifact::LocalArtifactResolver;
use audiagentic_core::{ApplicationInstanceId, ApplicationManifest};
use audiagentic_runtime::Runtime;

#[derive(Debug)]
struct ExternalState {
    locked_digest: String,
}

fn main() {
    let base_dir = Path::new(env!("CARGO_MANIFEST_DIR"));
    let manifest: ApplicationManifest =
        serde_json::from_str(include_str!("../audiagentic.json")).expect("valid app manifest");
    let prepared =
        Runtime::prepare(manifest, base_dir, &LocalArtifactResolver).expect("prepare application");
    let application = prepared
        .instantiate(
            ApplicationInstanceId::try_from("external-demo-1").expect("valid instance id"),
            |_manifest, lock| {
                Ok::<_, Infallible>(ExternalState {
                    locked_digest: lock.components[0].digest.to_string(),
                })
            },
        )
        .expect("infallible state factory");

    assert_eq!(application.manifest().id.as_str(), "external-demo");
    assert!(application.state().locked_digest.starts_with("sha256:"));
    println!("EXTERNAL_APP_OK");
}
