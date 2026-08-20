//! Sensitive-value primitives independent of logging or transport stacks.

use std::{collections::BTreeMap, error::Error, fmt};

pub const REDACTED: &str = "[REDACTED]";

pub struct Secret<T>(T);

impl<T> Secret<T> {
    pub fn new(value: T) -> Self {
        Self(value)
    }

    pub fn expose(&self) -> &T {
        &self.0
    }

    pub fn into_inner(self) -> T {
        self.0
    }

    pub fn map<U>(self, map: impl FnOnce(T) -> U) -> Secret<U> {
        Secret(map(self.0))
    }
}

impl<T: Clone> Clone for Secret<T> {
    fn clone(&self) -> Self {
        Self(self.0.clone())
    }
}

impl<T> fmt::Debug for Secret<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("Secret([REDACTED])")
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct SensitiveKey(String);

impl SensitiveKey {
    pub fn new(value: impl Into<String>) -> Result<Self, SensitiveKeyError> {
        let value = value.into();
        if value.trim().is_empty() {
            return Err(SensitiveKeyError);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SensitiveKeyError;

impl fmt::Display for SensitiveKeyError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("sensitive key must not be empty")
    }
}

impl Error for SensitiveKeyError {}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RedactionPolicy {
    replacement: &'static str,
}

impl Default for RedactionPolicy {
    fn default() -> Self {
        Self {
            replacement: REDACTED,
        }
    }
}

impl RedactionPolicy {
    pub fn replacement(&self) -> &'static str {
        self.replacement
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SafeMetadata {
    values: BTreeMap<String, String>,
}

impl SafeMetadata {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn insert_public(&mut self, key: impl Into<String>, value: impl Into<String>) {
        self.values.insert(key.into(), value.into());
    }

    /// Record only the existence of a sensitive field; the sensitive value is
    /// intentionally not accepted by this API.
    pub fn insert_sensitive(&mut self, key: SensitiveKey) {
        self.values.insert(key.0, REDACTED.to_owned());
    }

    pub fn get(&self, key: &str) -> Option<&str> {
        self.values.get(key).map(String::as_str)
    }

    pub fn iter(&self) -> impl Iterator<Item = (&str, &str)> {
        self.values
            .iter()
            .map(|(key, value)| (key.as_str(), value.as_str()))
    }
}

pub fn redact_text<'a>(input: &str, secrets: impl IntoIterator<Item = &'a str>) -> String {
    secrets
        .into_iter()
        .filter(|secret| !secret.is_empty())
        .fold(input.to_owned(), |text, secret| {
            text.replace(secret, REDACTED)
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn secret_debug_never_exposes_value() {
        let secret = Secret::new("needle");
        let debug = format!("{secret:?}");
        assert!(!debug.contains("needle"));
        assert!(debug.contains(REDACTED));
    }

    #[test]
    fn safe_metadata_never_accepts_a_sensitive_value() {
        let mut metadata = SafeMetadata::new();
        metadata.insert_public("operation", "write");
        metadata.insert_sensitive(SensitiveKey::new("token").unwrap());
        assert_eq!(metadata.get("operation"), Some("write"));
        assert_eq!(metadata.get("token"), Some(REDACTED));
    }

    #[test]
    fn text_redaction_is_explicit_and_deterministic() {
        assert_eq!(redact_text("token=abc", ["abc"]), "token=[REDACTED]");
    }
}
