use std::collections::BTreeMap;

use async_trait::async_trait;
use audiagentic_foundation_sensitive_spike::Secret;
use audiagentic_secrets_api_spike::{SecretError, SecretRef, SecretStore};

#[derive(Clone, Default)]
pub struct MemorySecretStore {
    values: BTreeMap<String, String>,
}

impl MemorySecretStore {
    pub fn new(values: impl IntoIterator<Item = (String, String)>) -> Self {
        Self {
            values: values.into_iter().collect(),
        }
    }
}

#[async_trait]
impl SecretStore for MemorySecretStore {
    async fn resolve(&self, reference: &SecretRef) -> Result<Secret<String>, SecretError> {
        self.values
            .get(reference.as_str())
            .cloned()
            .map(Secret::new)
            .ok_or_else(|| SecretError::NotFound(reference.as_str().to_owned()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn resolved_secret_does_not_leak_through_debug_or_display() {
        let store = MemorySecretStore::new([("service/default".into(), "super-secret".into())]);
        let secret = store
            .resolve(&SecretRef::new("service/default").unwrap())
            .await
            .unwrap();
        assert_eq!(format!("{secret}"), "[REDACTED]");
        assert_eq!(format!("{secret:?}"), "Secret([REDACTED])");
        assert_eq!(secret.expose(), "super-secret");
    }
}
