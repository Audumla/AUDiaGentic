use std::{error::Error, fs};

use audiagentic_core::{Application, ApplicationId, ApplicationIdentity, ApplicationInstanceId};
use audiagentic_host::{FileHost, FileReadAuthority, FileWriteAuthority};
use audiagentic_host_native::NativeFileHost;
use audiagentic_reconcile::{Change, Desired, EffectId, Observed, OwnershipId, Plan, plan_replace};
use audiagentic_sensitive::{REDACTED, SafeMetadata, Secret, SensitiveKey};

#[derive(Debug)]
struct StateFeature {
    file_host: NativeFileHost,
    read_authority: FileReadAuthority,
    write_authority: FileWriteAuthority,
    token: Secret<String>,
    plan: Plan<Change<String>>,
}

fn main() -> Result<(), Box<dyn Error>> {
    let directory =
        std::env::temp_dir().join(format!("audiagentic-large-app-{}", std::process::id()));
    let path = directory.join("state.txt");
    let _ = fs::remove_dir_all(&directory);
    fs::create_dir_all(&directory)?;

    let observed = Observed("old".to_owned());
    let desired = Desired("new".to_owned());
    let plan = plan_replace(
        OwnershipId::new("large-app")?,
        EffectId::new("state-write")?,
        &observed,
        &desired,
    );

    let file_host = NativeFileHost;
    let read_authority = FileReadAuthority::new(&directory);
    let write_authority = FileWriteAuthority::new(&directory);
    file_host.write(&write_authority, &path, b"old")?;
    file_host.write(&write_authority, &path, desired.0.as_bytes())?;

    let mut metadata = SafeMetadata::new();
    metadata.insert_public("operation", "state-write");
    metadata.insert_sensitive(SensitiveKey::new("token")?);
    assert_eq!(metadata.get("token"), Some(REDACTED));

    let composition = StateFeature {
        file_host,
        read_authority,
        write_authority,
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

    assert_eq!(app.composition().read_authority.root(), directory.as_path());
    assert_eq!(app.composition().write_authority.root(), directory.as_path());
    assert_eq!(
        app.composition()
            .file_host
            .read(&app.composition().read_authority, &path)?,
        b"new"
    );
    assert_eq!(app.composition().plan.changes().len(), 1);
    assert!(!format!("{:?}", app.composition().token).contains("never-log-me"));

    fs::remove_dir_all(directory)?;
    println!("LARGE_APP_OK");
    Ok(())
}
