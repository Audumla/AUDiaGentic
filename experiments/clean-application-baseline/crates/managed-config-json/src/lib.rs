use std::{collections::BTreeMap, sync::Arc};

use async_trait::async_trait;
use audiagentic_filesystem_api_spike::{FileSystem, RelativePath};
use audiagentic_foundation_reconcile_spike::{Change, OwnedValue, plan};
use audiagentic_managed_config_api_spike::{ManagedConfig, ManagedConfigError, ReconcileOutcome};
use serde_json::{Map, Value};

#[derive(Clone)]
pub struct JsonManagedConfig {
    filesystem: Arc<dyn FileSystem>,
}

impl JsonManagedConfig {
    pub fn new(filesystem: Arc<dyn FileSystem>) -> Self {
        Self { filesystem }
    }

    async fn load_document(
        &self,
        document: &str,
    ) -> Result<Map<String, Value>, ManagedConfigError> {
        let path =
            RelativePath::new(document).map_err(|e| ManagedConfigError::Storage(e.to_string()))?;
        match self
            .filesystem
            .read_text(&path)
            .await
            .map_err(|e| ManagedConfigError::Storage(e.to_string()))?
        {
            None => Ok(Map::new()),
            Some(text) => serde_json::from_str::<Value>(&text)
                .map_err(|e| ManagedConfigError::Format(e.to_string()))?
                .as_object()
                .cloned()
                .ok_or_else(|| {
                    ManagedConfigError::Format("managed JSON document must be an object".into())
                }),
        }
    }

    async fn load_owners(
        &self,
        document: &str,
    ) -> Result<BTreeMap<String, String>, ManagedConfigError> {
        let path = ownership_path(document)?;
        match self
            .filesystem
            .read_text(&path)
            .await
            .map_err(|e| ManagedConfigError::Storage(e.to_string()))?
        {
            None => Ok(BTreeMap::new()),
            Some(text) => {
                serde_json::from_str(&text).map_err(|e| ManagedConfigError::Format(e.to_string()))
            }
        }
    }

    async fn save(
        &self,
        document: &str,
        values: &Map<String, Value>,
        owners: &BTreeMap<String, String>,
    ) -> Result<(), ManagedConfigError> {
        let document_path =
            RelativePath::new(document).map_err(|e| ManagedConfigError::Storage(e.to_string()))?;
        let owner_path = ownership_path(document)?;
        let document_text = serde_json::to_string_pretty(&Value::Object(values.clone()))
            .map_err(|e| ManagedConfigError::Format(e.to_string()))?;
        let owner_text = serde_json::to_string_pretty(owners)
            .map_err(|e| ManagedConfigError::Format(e.to_string()))?;

        self.filesystem
            .write_text_atomic(&document_path, document_text)
            .await
            .map_err(|e| ManagedConfigError::Storage(e.to_string()))?;
        self.filesystem
            .write_text_atomic(&owner_path, owner_text)
            .await
            .map_err(|e| ManagedConfigError::Storage(e.to_string()))?;
        Ok(())
    }
}

#[async_trait]
impl ManagedConfig for JsonManagedConfig {
    async fn ensure_value(
        &self,
        document: &str,
        key: &str,
        owner: &str,
        value: Value,
    ) -> Result<ReconcileOutcome, ManagedConfigError> {
        let mut values = self.load_document(document).await?;
        let mut owners = self.load_owners(document).await?;

        let observed = values.get(key).cloned().map(|value| OwnedValue {
            owner: owners
                .get(key)
                .cloned()
                .unwrap_or_else(|| "user".to_owned()),
            value,
        });
        let desired = Some(OwnedValue {
            owner: owner.to_owned(),
            value,
        });

        match plan(observed, desired) {
            Change::Noop => Ok(ReconcileOutcome::Unchanged),
            Change::Conflict { .. } => Err(ManagedConfigError::Conflict(key.to_owned())),
            Change::Create { desired } => {
                values.insert(key.to_owned(), desired.value);
                owners.insert(key.to_owned(), desired.owner);
                self.save(document, &values, &owners).await?;
                Ok(ReconcileOutcome::Created)
            }
            Change::Update { desired, .. } => {
                values.insert(key.to_owned(), desired.value);
                owners.insert(key.to_owned(), desired.owner);
                self.save(document, &values, &owners).await?;
                Ok(ReconcileOutcome::Updated)
            }
            Change::Remove { .. } => unreachable!("ensure always supplies desired state"),
        }
    }

    async fn remove_owned(
        &self,
        document: &str,
        key: &str,
        owner: &str,
    ) -> Result<ReconcileOutcome, ManagedConfigError> {
        let mut values = self.load_document(document).await?;
        let mut owners = self.load_owners(document).await?;
        let Some(value) = values.get(key).cloned() else {
            return Ok(ReconcileOutcome::Unchanged);
        };
        let current_owner = owners
            .get(key)
            .cloned()
            .unwrap_or_else(|| "user".to_owned());
        let observed = Some(OwnedValue {
            owner: current_owner,
            value,
        });

        match plan(observed, None) {
            Change::Remove { before } if before.owner == owner => {
                values.remove(key);
                owners.remove(key);
                self.save(document, &values, &owners).await?;
                Ok(ReconcileOutcome::Removed)
            }
            Change::Remove { .. } => Err(ManagedConfigError::Conflict(key.to_owned())),
            Change::Noop => Ok(ReconcileOutcome::Unchanged),
            _ => unreachable!("remove has observed state and no desired state"),
        }
    }
}

fn ownership_path(document: &str) -> Result<RelativePath, ManagedConfigError> {
    RelativePath::new(format!("{document}.audiagentic-owners.json"))
        .map_err(|e| ManagedConfigError::Storage(e.to_string()))
}

#[cfg(test)]
mod tests {
    use std::sync::{Arc, Mutex};

    use audiagentic_filesystem_api_spike::{FileSystemError, RelativePath};

    use super::*;

    #[derive(Default)]
    struct MemoryFileSystem {
        files: Mutex<BTreeMap<String, String>>,
    }

    #[async_trait]
    impl FileSystem for MemoryFileSystem {
        async fn read_text(&self, path: &RelativePath) -> Result<Option<String>, FileSystemError> {
            Ok(self
                .files
                .lock()
                .unwrap()
                .get(&path.as_path().display().to_string())
                .cloned())
        }

        async fn write_text_atomic(
            &self,
            path: &RelativePath,
            content: String,
        ) -> Result<(), FileSystemError> {
            self.files
                .lock()
                .unwrap()
                .insert(path.as_path().display().to_string(), content);
            Ok(())
        }

        async fn remove_file(&self, path: &RelativePath) -> Result<bool, FileSystemError> {
            Ok(self
                .files
                .lock()
                .unwrap()
                .remove(&path.as_path().display().to_string())
                .is_some())
        }
    }

    #[tokio::test]
    async fn preserves_user_values_and_refuses_to_claim_them() {
        let filesystem = Arc::new(MemoryFileSystem::default());
        filesystem
            .write_text_atomic(
                &RelativePath::new("settings.json").unwrap(),
                r#"{"user_key":"keep"}"#.into(),
            )
            .await
            .unwrap();
        let managed = JsonManagedConfig::new(filesystem.clone());

        let result = managed
            .ensure_value(
                "settings.json",
                "user_key",
                "app",
                Value::String("replace".into()),
            )
            .await;
        assert_eq!(result, Err(ManagedConfigError::Conflict("user_key".into())));

        managed
            .ensure_value("settings.json", "managed_key", "app", Value::Bool(true))
            .await
            .unwrap();
        let stored = filesystem
            .read_text(&RelativePath::new("settings.json").unwrap())
            .await
            .unwrap()
            .unwrap();
        let stored: Value = serde_json::from_str(&stored).unwrap();
        assert_eq!(stored["user_key"], "keep");
        assert_eq!(stored["managed_key"], true);
    }

    #[tokio::test]
    async fn only_owner_can_remove_managed_value() {
        let filesystem = Arc::new(MemoryFileSystem::default());
        let managed = JsonManagedConfig::new(filesystem);
        assert_eq!(
            managed
                .ensure_value("settings.json", "managed", "app", Value::Bool(true))
                .await
                .unwrap(),
            ReconcileOutcome::Created
        );
        assert!(matches!(
            managed
                .remove_owned("settings.json", "managed", "other")
                .await,
            Err(ManagedConfigError::Conflict(_))
        ));
        assert_eq!(
            managed
                .remove_owned("settings.json", "managed", "app")
                .await
                .unwrap(),
            ReconcileOutcome::Removed
        );
    }
}
