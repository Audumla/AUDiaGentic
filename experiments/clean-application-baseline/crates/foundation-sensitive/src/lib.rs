use std::fmt;

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
}

impl<T> fmt::Debug for Secret<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("Secret([REDACTED])")
    }
}

impl<T> fmt::Display for Secret<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("[REDACTED]")
    }
}

pub fn is_sensitive_key(key: &str) -> bool {
    let key = key.to_ascii_lowercase();
    ["token", "secret", "password", "passwd", "api_key", "apikey", "authorization", "credential"]
        .iter()
        .any(|needle| key.contains(needle))
}

pub fn redact_pairs<I, K, V>(pairs: I) -> Vec<(String, String)>
where
    I: IntoIterator<Item = (K, V)>,
    K: Into<String>,
    V: Into<String>,
{
    pairs
        .into_iter()
        .map(|(key, value)| {
            let key = key.into();
            let value = if is_sensitive_key(&key) {
                "[REDACTED]".to_owned()
            } else {
                value.into()
            };
            (key, value)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn secret_never_debugs_or_displays_plaintext() {
        let secret = Secret::new("hunter2".to_owned());
        assert_eq!(format!("{secret}"), "[REDACTED]");
        assert_eq!(format!("{secret:?}"), "Secret([REDACTED])");
        assert_eq!(secret.expose(), "hunter2");
    }

    #[test]
    fn known_sensitive_keys_are_redacted() {
        let redacted = redact_pairs([("api_key", "abc"), ("model", "qwen")]);
        assert_eq!(redacted[0].1, "[REDACTED]");
        assert_eq!(redacted[1].1, "qwen");
    }
}
