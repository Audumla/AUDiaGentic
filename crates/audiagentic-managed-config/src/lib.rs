//! Managed configuration reconciliation over narrow file-host authority.
//!
//! This capability composes `audiagentic-reconcile` with `FileHost`; it does not
//! own a configuration registry, watcher, scheduler, parser, or global manager.
//! Applications own target definitions, desired bytes, retry policy, and any
//! concurrency/CAS requirements stronger than this single-writer primitive.

use std::{
    error::Error,
    fmt,
    path::{Path, PathBuf},
};

use audiagentic_host::{FileHost, FileReadAuthority, FileWriteAuthority};
use audiagentic_reconcile::{
    Change, Desired, EffectId, Observed, OwnershipId, Plan, Receipt, plan_presence,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ManagedConfigTarget {
    path: PathBuf,
    ownership: OwnershipId,
}

impl ManagedConfigTarget {
    pub fn new(path: impl Into<PathBuf>, ownership: OwnershipId) -> Self {
        Self {
            path: path.into(),
            ownership,
        }
    }

    pub fn path(&self) -> &Path {
        &self.path
    }

    pub fn ownership(&self) -> &OwnershipId {
        &self.ownership
    }
}

pub type ConfigObserved = Observed<Option<Vec<u8>>>;
pub type ConfigDesired = Desired<Option<Vec<u8>>>;
pub type ConfigPlan = Plan<Change<Vec<u8>>>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ConfigApplyResult {
    Noop,
    Created,
    Replaced,
    Deleted,
}

#[derive(Debug)]
pub enum ManagedConfigError<E> {
    Host(E),
    OwnershipMismatch {
        expected: OwnershipId,
        actual: OwnershipId,
    },
    InvalidPlanShape(usize),
}

impl<E: fmt::Display> fmt::Display for ManagedConfigError<E> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Host(error) => write!(f, "managed config host error: {error}"),
            Self::OwnershipMismatch { expected, actual } => write!(
                f,
                "managed config ownership mismatch: expected {}, actual {}",
                expected.as_str(),
                actual.as_str()
            ),
            Self::InvalidPlanShape(changes) => write!(
                f,
                "managed config plan must contain at most one change, got {changes}"
            ),
        }
    }
}

impl<E: Error + 'static> Error for ManagedConfigError<E> {}

pub fn observe<H: FileHost>(
    host: &H,
    authority: &FileReadAuthority,
    target: &ManagedConfigTarget,
) -> Result<ConfigObserved, H::Error> {
    host.read_optional(authority, target.path()).map(Observed)
}

pub fn plan(
    target: &ManagedConfigTarget,
    effect: EffectId,
    observed: &ConfigObserved,
    desired: &ConfigDesired,
) -> ConfigPlan {
    plan_presence(target.ownership().clone(), effect, observed, desired)
}

pub fn apply<H: FileHost>(
    host: &H,
    authority: &FileWriteAuthority,
    target: &ManagedConfigTarget,
    plan: &ConfigPlan,
) -> Result<Receipt<ConfigApplyResult>, ManagedConfigError<H::Error>> {
    if plan.ownership() != target.ownership() {
        return Err(ManagedConfigError::OwnershipMismatch {
            expected: target.ownership().clone(),
            actual: plan.ownership().clone(),
        });
    }

    let result = match plan.changes() {
        [] => ConfigApplyResult::Noop,
        [Change::Create { after }] => {
            host.write(authority, target.path(), after)
                .map_err(ManagedConfigError::Host)?;
            ConfigApplyResult::Created
        }
        [Change::Replace { after, .. }] => {
            host.write(authority, target.path(), after)
                .map_err(ManagedConfigError::Host)?;
            ConfigApplyResult::Replaced
        }
        [Change::Delete { .. }] => {
            host.remove(authority, target.path())
                .map_err(ManagedConfigError::Host)?;
            ConfigApplyResult::Deleted
        }
        changes => return Err(ManagedConfigError::InvalidPlanShape(changes.len())),
    };

    Ok(Receipt::new(plan.effect().clone(), result))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{collections::BTreeMap, io, sync::Mutex};

    #[derive(Default)]
    struct MemoryFileHost {
        files: Mutex<BTreeMap<PathBuf, Vec<u8>>>,
    }

    impl FileHost for MemoryFileHost {
        type Error = io::Error;

        fn read(
            &self,
            _authority: &FileReadAuthority,
            path: &Path,
        ) -> Result<Vec<u8>, Self::Error> {
            self.files
                .lock()
                .unwrap()
                .get(path)
                .cloned()
                .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "missing"))
        }

        fn read_optional(
            &self,
            _authority: &FileReadAuthority,
            path: &Path,
        ) -> Result<Option<Vec<u8>>, Self::Error> {
            Ok(self.files.lock().unwrap().get(path).cloned())
        }

        fn write(
            &self,
            _authority: &FileWriteAuthority,
            path: &Path,
            bytes: &[u8],
        ) -> Result<(), Self::Error> {
            self.files
                .lock()
                .unwrap()
                .insert(path.to_path_buf(), bytes.to_vec());
            Ok(())
        }

        fn remove(&self, _authority: &FileWriteAuthority, path: &Path) -> Result<(), Self::Error> {
            self.files.lock().unwrap().remove(path);
            Ok(())
        }
    }

    fn target() -> ManagedConfigTarget {
        ManagedConfigTarget::new(
            "config/app.conf",
            OwnershipId::new("application-config").unwrap(),
        )
    }

    fn read_authority() -> FileReadAuthority {
        FileReadAuthority::new("config")
    }

    fn write_authority() -> FileWriteAuthority {
        FileWriteAuthority::new("config")
    }

    fn effect(value: &str) -> EffectId {
        EffectId::new(value).unwrap()
    }

    #[test]
    fn create_replace_delete_flow_is_explicit() {
        let host = MemoryFileHost::default();
        let target = target();

        let observed = observe(&host, &read_authority(), &target).unwrap();
        let create = plan(
            &target,
            effect("create"),
            &observed,
            &Desired(Some(b"one".to_vec())),
        );
        assert_eq!(
            apply(&host, &write_authority(), &target, &create)
                .unwrap()
                .result(),
            &ConfigApplyResult::Created
        );

        let observed = observe(&host, &read_authority(), &target).unwrap();
        let replace = plan(
            &target,
            effect("replace"),
            &observed,
            &Desired(Some(b"two".to_vec())),
        );
        assert_eq!(
            apply(&host, &write_authority(), &target, &replace)
                .unwrap()
                .result(),
            &ConfigApplyResult::Replaced
        );

        let observed = observe(&host, &read_authority(), &target).unwrap();
        let delete = plan(&target, effect("delete"), &observed, &Desired(None));
        assert_eq!(
            apply(&host, &write_authority(), &target, &delete)
                .unwrap()
                .result(),
            &ConfigApplyResult::Deleted
        );
        assert_eq!(observe(&host, &read_authority(), &target).unwrap().0, None);
    }

    #[test]
    fn unchanged_desired_bytes_produce_noop_receipt() {
        let host = MemoryFileHost::default();
        let target = target();
        host.write(&write_authority(), target.path(), b"same")
            .unwrap();

        let observed = observe(&host, &read_authority(), &target).unwrap();
        let plan = plan(
            &target,
            effect("noop"),
            &observed,
            &Desired(Some(b"same".to_vec())),
        );
        assert!(plan.is_noop());
        assert_eq!(
            apply(&host, &write_authority(), &target, &plan)
                .unwrap()
                .result(),
            &ConfigApplyResult::Noop
        );
    }
}
