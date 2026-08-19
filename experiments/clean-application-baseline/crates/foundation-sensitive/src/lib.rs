use std::fmt;

pub struct Secret<T>(T);

impl<T> Secret<T> {
    pub fn new(value: T) -> Self {
        Self(value)
    }

    pub fn expose_secret(&self) -> &T {
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

pub fn redact_text(input: &str, secrets: &[&str]) -> String {
    secrets
        .iter()
        .filter(|secret| !secret.is_empty())
        .fold(input.to_owned(), |text, secret| {
            text.replace(secret, "[REDACTED]")
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn secret_never_formats_inner_value() {
        let secret = Secret::new("swordfish".to_owned());
        assert_eq!(format!("{secret}"), "[REDACTED]");
        assert_eq!(format!("{secret:?}"), "Secret([REDACTED])");
        assert_eq!(secret.expose_secret(), "swordfish");
    }

    #[test]
    fn text_redaction_is_explicit_and_non_destructive_to_source() {
        let source = "token=swordfish other=value";
        let redacted = redact_text(source, &["swordfish"]);
        assert_eq!(redacted, "token=[REDACTED] other=value");
        assert_eq!(source, "token=swordfish other=value");
    }
}
