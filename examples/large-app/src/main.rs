use std::{error::Error, fs, path::PathBuf};

use audiagentic_core::{Application, ApplicationId, ApplicationIdentity, ApplicationInstanceId};
use audiagentic_file_store::{read, write_atomic};
use audiagentic_host::FileWriteAuthority;
use audiagentic_reconcile::{Change, Desired, EffectId, Observed, OwnershipId, Plan, plan_replace};
use audiagentic_sensitive::{REDACTED, SafeMetadata, Secret, SensitiveKey};

#[derive(Debug)]
struct StateFeature {
    authority: FileWriteAuthority,
    token: Secret<String>,
    plan: Plan<Change<String>>,
}

fn main() -> Result<(), Box<dyn Error>> {
    let directory = std::env::temp_dir().join(format!(
        "audiagentic-large-app-{}",
        std::process::id()
    ));
    let path = directory.join("state.txt");
    let _ = fs::remove_dir_all(&directory);

    let observed = Observed("old".to_owned());
    let desired = Desired("new".to_owned());
    let plan = plan_replace(
        OwnershipId::new("large-app")?,
        EffectId::new("state-write")?,
        &observed,
        &desired,
    );
    write_atomic(&path, desired.0.as_bytes())?;

    let mut metadata = SafeMetadata::new();
    metadata.insert_public("operation", "state-write");
    metadata.insert_sensitive(SensitiveKey::new("token")?);
    assert_eq!(metadata.get("token"), Some(REDACTED));

    let composition = StateFeature {
        authority: FileWriteAuthority::new(PathBuf::from(&directory)),
        token: Secret::new("never-log-me".to_owned()),
        plan,
    };
    let app = Application::new(
        ApplicationIdentity::new(
            ApplicationId::new("large-state-app")?,
            ApplicationInstanceId::new("local")?,
        ),
        composition,
    );

    assert_eq!(app.composition().authority.root(), directory.as_path());
    assert_eq!(read(&path)?, b"new");
    assert_eq!(app.composition().plan.changes().len(), 1);
    assert!(!format!("{:?}", app.composition().token).contains("never-log-me"));

    fs::remove_dir_all(directory)?;
    println!("LARGE_APP_OK");
    Ok(())
}
