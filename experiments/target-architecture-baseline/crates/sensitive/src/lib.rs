#![forbid(unsafe_code)]

use std::sync::LazyLock;

use regex::Regex;
use serde_json::Value;

pub use secrecy::{ExposeSecret, SecretString};

pub const REDACTED: &str = "[REDACTED]";

static URL_CREDENTIALS: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(https?://)[^@/\s]+:[^@/\s]+@")
        .expect("URL credential redaction regex must compile")
});
static KEY_VALUE_SECRET: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(\b(?:api[_-]?key|token|secret|password|authorization|auth)\b\s*[:=]\s*)\S+")
        .expect("key/value redaction regex must compile")
});
static BEARER_SECRET: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(bearer\s+)[A-Za-z0-9._-]{20,}").expect("bearer redaction regex must compile")
});
static PREFIXED_SECRET: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"\b(?:sk|pk|ghp|gho|ghu|ghs|ghr)-[A-Za-z0-9_-]{20,}\b")
        .expect("prefixed secret redaction regex must compile")
});

#[derive(Clone, Debug, Default)]
pub struct Redactor {
    literals: Vec<String>,
}

impl Redactor {
    pub fn new() -> Self {
        Self::default()
    }

    /// Register a known secret literal. Longer literals are replaced first.
    pub fn with_literal(mut self, literal: impl Into<String>) -> Self {
        let literal = literal.into();
        if !literal.is_empty() {
            self.literals.push(literal);
            self.literals
                .sort_by_key(|value| std::cmp::Reverse(value.len()));
            self.literals.dedup();
        }
        self
    }

    pub fn redact(&self, text: &str) -> String {
        let mut output = text.to_owned();
        for literal in &self.literals {
            output = output.replace(literal, REDACTED);
        }
        output = URL_CREDENTIALS
            .replace_all(&output, "$1[REDACTED]@")
            .into_owned();
        output = KEY_VALUE_SECRET
            .replace_all(&output, "$1[REDACTED]")
            .into_owned();
        output = BEARER_SECRET
            .replace_all(&output, "$1[REDACTED]")
            .into_owned();
        PREFIXED_SECRET.replace_all(&output, REDACTED).into_owned()
    }

    pub fn redact_json(&self, value: &Value) -> Value {
        match value {
            Value::Object(map) => Value::Object(
                map.iter()
                    .map(|(key, nested)| {
                        let value = if is_sensitive_key(key) {
                            Value::String(REDACTED.to_owned())
                        } else {
                            self.redact_json(nested)
                        };
                        (key.clone(), value)
                    })
                    .collect(),
            ),
            Value::Array(items) => {
                Value::Array(items.iter().map(|item| self.redact_json(item)).collect())
            }
            Value::String(text) => Value::String(self.redact(text)),
            other => other.clone(),
        }
    }
}

pub fn is_sensitive_key(key: &str) -> bool {
    let normalized = key.to_ascii_lowercase();
    [
        "key",
        "token",
        "secret",
        "password",
        "authorization",
        "auth",
    ]
    .iter()
    .any(|needle| normalized.contains(needle))
}

pub fn truncate_output(text: &str, max_chars: usize) -> String {
    let total = text.chars().count();
    if total <= max_chars {
        return text.to_owned();
    }
    let prefix: String = text.chars().take(max_chars).collect();
    format!("{prefix}\n... [truncated, {total} chars total]")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn redacts_known_literals_and_common_secret_shapes() {
        let redactor = Redactor::new().with_literal("literal-super-secret");
        let text = "password=hunter2 token: abcdefghijklmnopqrstuvwxyz https://u:p@example.test literal-super-secret";
        let output = redactor.redact(text);
        assert!(!output.contains("hunter2"));
        assert!(!output.contains("abcdefghijklmnopqrstuvwxyz"));
        assert!(!output.contains("u:p@"));
        assert!(!output.contains("literal-super-secret"));
        assert!(output.contains("https://[REDACTED]@example.test"));
    }

    #[test]
    fn structural_redaction_uses_key_policy() {
        let value = json!({
            "name": "demo",
            "api_key": "do-not-print",
            "nested": {"authorization": "Bearer 123"}
        });
        let redacted = Redactor::new().redact_json(&value);
        assert_eq!(redacted["name"], "demo");
        assert_eq!(redacted["api_key"], REDACTED);
        assert_eq!(redacted["nested"]["authorization"], REDACTED);
    }

    #[test]
    fn secret_string_debug_does_not_expose_the_secret() {
        let secret = SecretString::new("extremely-private".to_owned().into_boxed_str());
        let debug = format!("{secret:?}");
        assert!(!debug.contains("extremely-private"));
    }

    #[test]
    fn truncation_is_unicode_safe() {
        assert_eq!(
            truncate_output("åßç∂é", 3),
            "åßç\n... [truncated, 5 chars total]"
        );
    }
}
