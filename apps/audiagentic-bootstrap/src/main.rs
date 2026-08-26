use std::{error::Error, fs, io};

use audiacore_managed_content::ManagedContentApplyResult;
use audiagentic_bootstrap::{build_application, run_bootstrap};

fn main() -> Result<(), Box<dyn Error>> {
    let root = std::env::temp_dir().join(format!("audiagentic-bootstrap-{}", std::process::id()));
    if root.exists() {
        fs::remove_dir_all(&root)?;
    }
    fs::create_dir_all(&root)?;

    let result = (|| -> Result<(), Box<dyn Error>> {
        let mut application = build_application(root.clone())?;
        let first = run_bootstrap(&mut application, b"ready", 1)?;
        let second = run_bootstrap(&mut application, b"ready", 2)?;

        if first.apply_result != ManagedContentApplyResult::Created {
            return Err(io::Error::other("first bootstrap application was not created").into());
        }
        if second.apply_result != ManagedContentApplyResult::Noop {
            return Err(io::Error::other("second bootstrap application was not a noop").into());
        }
        if application.composition().events().len() != 2 {
            return Err(io::Error::other("bootstrap event stream did not record both runs").into());
        }

        println!(
            "AUDIAGENTIC_BOOTSTRAP_OK application={} first=created second=noop events=2",
            application.id()
        );
        Ok(())
    })();

    let cleanup = fs::remove_dir_all(&root);
    result?;
    cleanup?;
    Ok(())
}
