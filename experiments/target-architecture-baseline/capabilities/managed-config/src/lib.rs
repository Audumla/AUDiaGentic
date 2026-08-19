#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use audiagentic_file_store::{FileStoreError, atomic_write_json, read_json};
use audiagentic_reconcile::{Change, Conflict, DesiredSet, OwnershipRegistry, Plan, Receipt, plan};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use thiserror::Error;

const OWNERSHIP_CONTRACT_VERSION: u32 = 1;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
struct OwnershipFile {
    contract_version: u32,
    registry: OwnershipRegistry,
}

impl Default for OwnershipFile {
    fn default() -> Self {
        Self {
            contract_version: OWNERSHIP_CONTRACT_VERSION,
            registry: OwnershipRegistry::default(),
        }
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct SyncOutcome {
    pub changed: bool,
    pub updated: Vec<String>,
    pub removed: Vec<String>,
    pub conflicts: Vec<Conflict>,
    pub receipt: Option<Receipt<Value>>,
}

impl SyncOutcome {
    pub fn ok(&self) -> bool {
        self.conflicts.is_empty()
    }
}

#[derive(Debug, Error)]
pub enum ManagedConfigError {
    #[error(transparent)]
    Store(#[from] FileStoreError),
    #[error("managed config at {path} must contain a JSON object")]
    TargetNotObject { path: PathBuf },
    #[error("ownership registry at {path} has contract version {actual}, expected {expected}")]
    OwnershipVersion {
        path: PathBuf,
        actual: u32,
        expected: u32,
    },
}

/// Reconcile a named-entry JSON object while keeping ownership evidence in a
/// separate sidecar file.
///
/// The target is user-owned: entries absent from ownership evidence are never
/// overwritten or removed. A conflicting plan is returned without mutating
/// either file. Individual file replacements are atomic; cross-file crash
/// atomicity is deliberately not claimed here and belongs to a future durable
/// effect journal.
pub fn sync_json(
    target_path: impl AsRef<Path>,
    ownership_path: impl AsRef<Path>,
    desired: &DesiredSet<Value>,
) -> Result<SyncOutcome, ManagedConfigError> {
    let target_path = target_path.as_ref();
    let ownership_path = ownership_path.as_ref();
    let mut observed = read_target(target_path)?;
    let ownership = read_ownership(ownership_path)?;
    let planned = plan(desired, &observed, &ownership.registry);

    if !planned.is_safe() {
        return Ok(SyncOutcome {
            changed: false,
            updated: Vec::new(),
            removed: Vec::new(),
            conflicts: planned.conflicts,
            receipt: None,
        });
    }

    let (updated, removed) = apply_plan(&mut observed, &planned);
    let registry_changed = planned.next_registry != ownership.registry;
    if planned.changed() {
        atomic_write_json(target_path, &observed)?;
    }
    if registry_changed {
        atomic_write_json(
            ownership_path,
            &OwnershipFile {
                contract_version: OWNERSHIP_CONTRACT_VERSION,
                registry: planned.next_registry.clone(),
            },
        )?;
    }

    Ok(SyncOutcome {
        changed: planned.changed() || registry_changed,
        updated,
        removed,
        conflicts: Vec::new(),
        receipt: Receipt::from_plan(&planned),
    })
}

fn read_target(path: &Path) -> Result<BTreeMap<String, Value>, ManagedConfigError> {
    let Some(value) = read_json::<Value>(path)? else {
        return Ok(BTreeMap::new());
    };
    let Value::Object(map) = value else {
        return Err(ManagedConfigError::TargetNotObject {
            path: path.to_owned(),
        });
    };
    Ok(map.into_iter().collect())
}

fn read_ownership(path: &Path) -> Result<OwnershipFile, ManagedConfigError> {
    let Some(state) = read_json::<OwnershipFile>(path)? else {
        return Ok(OwnershipFile::default());
    };
    if state.contract_version != OWNERSHIP_CONTRACT_VERSION {
        return Err(ManagedConfigError::OwnershipVersion {
            path: path.to_owned(),
            actual: state.contract_version,
            expected: OWNERSHIP_CONTRACT_VERSION,
        });
    }
    Ok(state)
}

fn apply_plan(
    observed: &mut BTreeMap<String, Value>,
    planned: &Plan<Value>,
) -> (Vec<String>, Vec<String>) {
    let mut updated = Vec::new();
    let mut removed = Vec::new();
    for change in &planned.changes {
        match change {
            Change::Upsert { name, after, .. } => {
                observed.insert(name.clone(), after.clone());
                updated.push(name.clone());
            }
            Change::Remove { name, .. } => {
                observed.remove(name);
                removed.push(name.clone());
            }
        }
    }
    (updated, removed)
}

pub fn object(entries: BTreeMap<String, Value>) -> Value {
    Value::Object(entries.into_iter().collect::<Map<String, Value>>())
}

#[cfg(test)]
mod tests {
    use super::*;
    use audiagentic_reconcile::{DesiredItem, ManagedId, OwnerId};
    use serde_json::json;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn test_dir(label: &str) -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir().join(format!(
            "audiagentic-managed-config-{label}-{}-{nonce}",
            std::process::id()
        ))
    }

    fn desired(name: &str, value: Value) -> DesiredSet<Value> {
        DesiredSet::new(
            OwnerId::new("demo-app").unwrap(),
            BTreeMap::from([(
                ManagedId::new("stable-server-id").unwrap(),
                DesiredItem::new(name, value),
            )]),
        )
    }

    #[test]
    fn preserves_user_entries_and_supports_stable_id_rename() {
        let dir = test_dir("rename");
        let target = dir.join("tool.json");
        let ownership = dir.join("runtime/owners.json");
        atomic_write_json(&target, &json!({"user": {"keep": true}})).unwrap();

        let first = sync_json(
            &target,
            &ownership,
            &desired("old", json!({"command": "one"})),
        )
        .unwrap();
        assert!(first.ok());
        assert!(first.changed);

        let second = sync_json(
            &target,
            &ownership,
            &desired("new", json!({"command": "two"})),
        )
        .unwrap();
        assert!(second.ok());
        assert!(second.updated.contains(&"new".to_owned()));
        assert!(second.removed.contains(&"old".to_owned()));

        let result = read_json::<Value>(&target).unwrap().unwrap();
        assert_eq!(result["user"], json!({"keep": true}));
        assert!(result.get("old").is_none());
        assert_eq!(result["new"], json!({"command": "two"}));
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn collision_with_user_entry_aborts_without_mutation() {
        let dir = test_dir("collision");
        let target = dir.join("tool.json");
        let ownership = dir.join("runtime/owners.json");
        let original = json!({"existing": {"user": true}});
        atomic_write_json(&target, &original).unwrap();

        let outcome = sync_json(
            &target,
            &ownership,
            &desired("existing", json!({"managed": true})),
        )
        .unwrap();
        assert!(!outcome.ok());
        assert!(!outcome.changed);
        assert_eq!(read_json::<Value>(&target).unwrap(), Some(original));
        assert!(!ownership.exists());
        fs::remove_dir_all(dir).unwrap();
    }
}
